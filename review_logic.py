"""Officer review rules for choosing verified CGHS codes and payable amounts."""
from matcher import extract_cghs_code, get_rate, confident_description_match

AUTOMATIC = "Automatic fetching mode"
CODE_ONLY = "Code only mode"
CODE_BASED = "Automatic – Code Based"
MANUAL = "Manual"
NO_CODE = "Diagnosis/Description Based – No Code Available"


def resolve_item(row, by_code, descriptions, tier_label, accreditation, mode=AUTOMATIC,
                 diagnosis="", treatment_type=""):
    """Resolve a billed row while retaining officer control over uncertain codes.

    A matched-code picker is an officer confirmation. A billed code must exist in
    the rate master. The new code-based and manual modes do not infer codes.
    A diagnosis may inform suggestions in the UI, but cannot create a bill row
    or assign a procedure code without a billed description.
    """
    description = str(row.get("description") or "").strip()
    raw_code = str(row.get("billed_code") or "").strip()
    selected = str(row.get("matched_code") or "").strip()
    claimed = max(0, float(row.get("claimed_amount") or 0))
    billed = extract_cghs_code(raw_code, by_code)
    if selected in by_code:
        code, source = selected, "Manually selected/modified match"
    elif mode == MANUAL:
        code, source = None, "No reliable match found"
    else:
        code = billed
        source = "Exact/code-based match" if billed else ""
    score = 100 if code else None
    if not code and mode == CODE_ONLY:
        return None
    if not code and description and mode in (AUTOMATIC, NO_CODE):
        inferred_code, inferred_score = confident_description_match(
            description, descriptions, context=diagnosis,
            treatment_type=treatment_type if mode == NO_CODE else "")
        if inferred_code:
            code = inferred_code
            score = inferred_score
            source = "Description-based suggested match — review"
    rate = get_rate(by_code[code], tier_label, accreditation) if code else None
    return {
        "description": description, "billed_code": raw_code, "code": code,
        "claimed_amount": claimed, "cghs_rate": rate,
        "admissible_amount": min(claimed, rate) if rate is not None else None,
        "matched_description": by_code[code]["description"] if code else description,
        "match_source": source or "No reliable match found", "match_score": score,
        "override": row.get("override", "Auto"),
        "invoice_number": str(row.get("invoice_number") or "").strip().upper(),
        "service_date": str(row.get("service_date") or "").strip(),
        "source_page": row.get("source_page"),
        "line_number": str(row.get("line_number") or "").strip(),
    }
