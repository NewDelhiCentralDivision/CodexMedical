"""Officer review rules for choosing verified CGHS codes and payable amounts."""
from matcher import extract_cghs_code, get_rate, confident_description_match

AUTOMATIC = "Automatic fetching mode"
CODE_ONLY = "Code only mode"


def resolve_item(row, by_code, descriptions, tier_label, accreditation, mode=AUTOMATIC):
    """Return one reviewed row, or None when code-only excludes an uncoded entry.

    A matched-code picker is an officer confirmation. A billed code must exist in
    the rate master. Description inference is only allowed in automatic mode.
    """
    description = str(row.get("description") or "").strip()
    raw_code = str(row.get("billed_code") or "").strip()
    selected = str(row.get("matched_code") or "").strip()
    claimed = max(0, float(row.get("claimed_amount") or 0))
    billed = extract_cghs_code(raw_code, by_code)
    code = selected if selected in by_code else billed
    source = "Officer selected" if selected in by_code else "Printed code" if billed else ""
    score = 100 if code else None
    if not code and mode == CODE_ONLY:
        return None
    if not code and description:
        inferred_code, inferred_score = confident_description_match(description, descriptions)
        if inferred_code:
            code = inferred_code
            score = inferred_score
            source = "Description inferred — review"
    rate = get_rate(by_code[code], tier_label, accreditation) if code else None
    return {
        "description": description, "billed_code": raw_code, "code": code,
        "claimed_amount": claimed, "cghs_rate": rate,
        "admissible_amount": min(claimed, rate) if rate is not None else None,
        "matched_description": by_code[code]["description"] if code else description,
        "match_source": source or "No verified code", "match_score": score,
        "override": row.get("override", "Auto"),
        "invoice_number": str(row.get("invoice_number") or "").strip().upper(),
        "service_date": str(row.get("service_date") or "").strip(),
        "source_page": row.get("source_page"),
    }
