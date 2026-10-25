"""
CGHS rate matching engine (all-tier version).
Given a list of claimed line items (code and/or description + claimed amount),
matches each against the CGHS master rate table and computes the admissible
amount for a chosen city tier + accreditation, flagging overcharges,
no-matches, and likely duplicate billings.
"""
import json
import re
from rapidfuzz import fuzz, process

TIER_KEYS = {
    "Tier I (X City)": "tier1_x_city",
    "Tier II (Y City)": "tier2_y_city",
    "Tier III (Z City)": "tier3_z_city",
}

# Every CGHS code follows this exact shape: 2-4 uppercase letters then 3 digits
# (e.g. LB127, RI022, OP121, NS018, NU144, CN001). Real-world bills often print
# a second, unrelated internal lab code right alongside it (e.g. "R047 - LB127"),
# so rather than treating the whole billed-code string as the CGHS code, we pull
# out just the substring that matches this shape.
CGHS_CODE_PATTERN = re.compile(r'[A-Z]{2,4}\d{3}')

# Common billing abbreviations are rarely printed exactly like the CGHS master.
# Normalising them before fuzzy matching lets the system infer a *verified* CGHS
# code even when a claim contains only an abbreviated test name, never a code
# invented by the model.
MEDICAL_ALIASES = {
    r'\bcbc\b': 'complete haemogram', r'\bkft\b|\brft\b': 'kidney function test',
    r'\blft\b': 'liver function test', r'\btft\b': 'thyroid function test',
    r'\busg\b': 'ultrasonography', r'\bx[ -]?ray\b': 'radiography',
    r'\bct\b': 'computed tomography', r'\bmri\b': 'magnetic resonance imaging',
    r'\bhba1c\b': 'glycosylated haemoglobin', r'\btsh\b': 'thyroid stimulating hormone',
}


def normalise_description(text):
    """Make noisy bill text comparable with the official CGHS descriptions."""
    value = (text or '').lower()
    value = re.sub(r'[^a-z0-9+/. ]+', ' ', value)
    for pattern, replacement in MEDICAL_ALIASES.items():
        value = re.sub(pattern, replacement, value)
    return re.sub(r'\s+', ' ', value).strip()


def extract_cghs_code(text, valid_codes=None):
    """Find a CGHS-shaped code (AA123 style) inside a string that may also
    contain an unrelated internal lab/hospital code of the same rough shape
    (e.g. 'WZ786 - LB012', where WZ786 is the lab's own code and LB012 is the
    real CGHS code - both happen to fit the AA123 pattern).

    If valid_codes (a set/dict of real CGHS codes) is given, every candidate
    found is checked against it and the first one that's an actual CGHS code
    wins - this is what avoids picking the wrong one. Without valid_codes,
    falls back to the last pattern match in the string, since on real bills
    the CGHS code is conventionally printed second (internal code first).
    """
    if not text:
        return None
    candidates = CGHS_CODE_PATTERN.findall(text.upper())
    if not candidates:
        return None
    if valid_codes is not None:
        for c in candidates:
            if c in valid_codes:
                return c
        return None
    return candidates[-1]


def load_master(json_path):
    """Returns (raw_list, by_code, descriptions dict code->description)."""
    with open(json_path) as f:
        data = json.load(f)
    by_code = {r['code']: r for r in data}
    descriptions = {r['code']: r['description'] for r in data}
    return data, by_code, descriptions


def get_rate(rate_row, tier_label, accreditation):
    """
    rate_row: one record from the master list (has a 'tiers' dict)
    tier_label: one of TIER_KEYS' keys, e.g. "Tier I (X City)"
    accreditation: "NABH", "Non-NABH", or "Super Speciality"
    """
    tier_key = TIER_KEYS.get(tier_label, "tier1_x_city")
    tier_rates = rate_row.get('tiers', {}).get(tier_key)
    if not tier_rates:
        return None
    if accreditation == 'NABH':
        return tier_rates['rate_nabh']
    elif accreditation == 'Super Speciality':
        return tier_rates['rate_super_speciality']
    else:
        return tier_rates['rate_non_nabh']


def best_fuzzy_match(query, descriptions, score_cutoff=62):
    if not query or not query.strip():
        return None, 0
    clean_query = normalise_description(query)
    if not clean_query:
        return None, 0
    # Token set handles word order; WRatio is more resilient to OCR noise and
    # short bill descriptions. Pick the strongest score for each query.
    candidates = []
    for scorer in (fuzz.token_set_ratio, fuzz.WRatio):
        result = process.extractOne(clean_query, descriptions, scorer=scorer, score_cutoff=score_cutoff)
        if result:
            candidates.append((result[2], result[1]))
    if not candidates:
        return None, 0
    return max(candidates, key=lambda candidate: candidate[1])


def confident_description_match(query, descriptions):
    """Use a unique, stable rate-master match; leave ambiguous descriptions blank."""
    ranked = description_candidates(query, descriptions, limit=2)
    if not ranked:
        return None, 0
    best, second = ranked[0], ranked[1] if len(ranked) > 1 else (None, None, 0)
    if best[2] >= 90 and best[2] - second[2] >= 7:
        return best[0], best[2]
    return None, best[2]


def description_candidates(query, descriptions, limit=3, context=""):
    """Stable ranked suggestions; never assign a code from a generic label alone.

    Each result is (code, official description, score). Callers decide whether
    to accept a unique high-confidence match or ask the officer to choose.
    """
    clean = normalise_description(query)
    if len(clean) < 5 or clean in {"consultation", "investigation", "medicine", "medicines", "procedure", "test"}:
        return []
    ranked = []
    context_terms = {word for word in normalise_description(context).split() if len(word) >= 5}
    for code, description in descriptions.items():
        candidate = normalise_description(description)
        if candidate == clean:
            score = 100
        else:
            # A shorter catalogue entry can have a token-set score of 100
            # merely because its words occur inside a longer exact entry.
            # Keep exact descriptions decisively ahead of such partial hits.
            score = min(92, max(fuzz.WRatio(clean, candidate),
                                fuzz.token_set_ratio(clean, candidate)))
        if score >= 65 and context_terms and context_terms.intersection(candidate.split()):
            score = min(100, score + 2)  # context only breaks close suggestions
        ranked.append((code, description, score))
    ranked.sort(key=lambda pair: (-pair[2], pair[0]))
    return ranked[:limit]


def match_line_item(item, by_code, descriptions, tier_label="Tier I (X City)", accreditation="NABH"):
    """
    item: dict with optional 'code' and required 'description', 'claimed_amount'
    returns enriched dict with match info
    """
    code_raw = item.get('code', '')
    code = extract_cghs_code(code_raw, valid_codes=by_code)
    matched_code = None
    match_method = None
    score = None

    if code and code in by_code:
        matched_code = code
        match_method = 'exact_code'
        score = 100
    else:
        fm_code, fm_score = confident_description_match(item.get('description', ''), descriptions)
        if fm_code:
            matched_code = fm_code
            match_method = 'fuzzy_description'
            score = fm_score

    result = dict(item)
    if matched_code:
        rate_row = by_code[matched_code]
        cghs_rate = get_rate(rate_row, tier_label, accreditation)
        result.update({
            'matched_code': matched_code,
            'matched_description': rate_row['description'],
            'cghs_rate': cghs_rate,
            'match_method': match_method,
            'match_score': score,
            'admissible_amount': (min(item.get('claimed_amount', 0), cghs_rate)
                                   if (cghs_rate is not None and item.get('claimed_amount') is not None) else cghs_rate),
        })
        claimed = item.get('claimed_amount', 0) or 0
        if cghs_rate is not None and claimed > cghs_rate:
            result['flag'] = 'OVERCHARGED'
        elif match_method == 'fuzzy_description':
            result['flag'] = f'INFERRED FROM DESCRIPTION ({score:.0f}%) - REVIEW'
        else:
            result['flag'] = 'OK'
    else:
        result.update({
            'matched_code': None, 'matched_description': None,
            'cghs_rate': None,
            'match_method': 'none', 'match_score': 0,
            'admissible_amount': None,
            'flag': 'NO MATCH - MANUAL REVIEW REQUIRED'
        })
    return result


def flag_duplicates(matched_items):
    """Mark items sharing the same matched_code as potential duplicate billing.
    (Simple label only. The app itself now uses bundles.apply_billing_rules, which also
    understands packages that already include other tests and decides what is counted.)"""
    seen = {}
    for it in matched_items:
        c = it.get('matched_code')
        if c:
            seen.setdefault(c, []).append(it)
    for c, items in seen.items():
        if len(items) > 1:
            for it in items:
                if it['flag'] == 'OK':
                    it['flag'] = 'POSSIBLE DUPLICATE'
                else:
                    it['flag'] += ' + POSSIBLE DUPLICATE'
    return matched_items


def process_claim(line_items, master_json_path, tier_label="Tier I (X City)", accreditation="NABH"):
    """Whole-claim check without the UI: match every item, then apply the billing rules so a test
    that is already included in a package billed on the same claim (e.g. Hb inside a CBC), or
    a repeated diagnostic test, is not paid twice. Each returned item carries 'rule_status',
    'rule_note' and 'counted_amount'; the totals use 'counted_amount'."""
    from bundles import apply_billing_rules  # local import: bundles has no dependency on this module

    _, by_code, descriptions = load_master(master_json_path)
    matched = [match_line_item(it, by_code, descriptions, tier_label, accreditation) for it in line_items]
    ruled = apply_billing_rules(
        [{'code': m.get('matched_code'), 'claimed_amount': m.get('claimed_amount') or 0,
          'admissible_amount': m.get('admissible_amount')} for m in matched],
        by_code,
    )
    for m, r in zip(matched, ruled):
        m.update({'rule_status': r['rule_status'], 'rule_note': r['rule_note'],
                  'counted_amount': r['counted_amount'], 'covered_by': r['covered_by']})
    total_claimed = sum(it.get('claimed_amount') or 0 for it in matched)
    total_admissible = sum(it['counted_amount'] for it in matched if it['counted_amount'] is not None)
    return {
        'items': matched,
        'total_claimed': total_claimed,
        'total_admissible': total_admissible,
    }
