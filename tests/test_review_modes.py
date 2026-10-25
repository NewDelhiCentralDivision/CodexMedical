from matcher import description_candidates
from review_logic import (AUTOMATIC, CODE_ONLY, CODE_BASED, MANUAL,
                          NO_CODE, resolve_item)


RATES = {
    "LB012": {"code": "LB012", "description": "Complete Haemogram", "tiers": {
        "tier1_x_city": {"rate_nabh": 300, "rate_non_nabh": 250, "rate_super_speciality": 350}}}
}
DESCRIPTIONS = {"LB012": "Complete Haemogram"}
TIER = "Tier I (X City)"


def test_claim_below_cghs_cap_is_used():
    row = resolve_item({"description": "Complete Haemogram", "billed_code": "LB012",
                        "claimed_amount": 180}, RATES, DESCRIPTIONS, TIER, "NABH")
    assert row["admissible_amount"] == 180
    assert row["match_source"] == "Exact/code-based match"


def test_claim_above_cghs_cap_is_limited():
    row = resolve_item({"description": "Complete Haemogram", "billed_code": "LB012",
                        "claimed_amount": 500}, RATES, DESCRIPTIONS, TIER, "NABH")
    assert row["admissible_amount"] == 300


def test_code_only_omits_uncoded_entry():
    row = {"description": "Complete Haemogram", "claimed_amount": 180}
    assert resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", CODE_ONLY) is None
    inferred = resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", AUTOMATIC)
    assert inferred["code"] == "LB012"
    assert inferred["match_source"] == "Description-based suggested match — review"


def test_unknown_printed_code_cannot_become_calculation_code():
    row = {"description": "Unrelated service", "billed_code": "ZZ999", "claimed_amount": 100}
    assert resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", CODE_ONLY) is None
    assert resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", AUTOMATIC)["code"] is None


def test_new_code_based_mode_prefers_valid_code_and_keeps_invalid_row_visible():
    valid = resolve_item({"description": "different text", "billed_code": "LB012", "claimed_amount": 180},
                         RATES, DESCRIPTIONS, TIER, "NABH", CODE_BASED)
    assert valid["code"] == "LB012" and valid["admissible_amount"] == 180
    invalid = resolve_item({"description": "Complete Haemogram", "billed_code": "ZZ999",
                            "claimed_amount": 180}, RATES, DESCRIPTIONS, TIER, "NABH", CODE_BASED)
    assert invalid["code"] is None and invalid["admissible_amount"] is None


def test_no_code_mode_suggests_clear_description_and_manual_can_correct_it():
    row = {"description": "Complete Haemogram", "claimed_amount": 180}
    suggested = resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", NO_CODE)
    assert suggested["code"] == "LB012"
    assert suggested["match_source"] == "Description-based suggested match — review"
    rates = {**RATES, "LB013": {**RATES["LB012"], "code": "LB013",
                              "description": "Platelet Count"}}
    corrected = resolve_item({**row, "matched_code": "LB013"}, rates,
                              {**DESCRIPTIONS, "LB013": "Platelet Count"},
                              TIER, "NABH", NO_CODE)
    assert corrected["code"] == "LB013"
    assert corrected["match_source"] == "Manually selected/modified match"


def test_ambiguous_and_unrelated_descriptions_remain_unmatched():
    descriptions = {"RI101": "CT scan abdomen with contrast",
                    "RI102": "CT scan abdomen without contrast"}
    rates = {code: {**RATES["LB012"], "code": code, "description": description}
             for code, description in descriptions.items()}
    ambiguous = resolve_item({"description": "CT scan abdomen", "claimed_amount": 100},
                              rates, descriptions, TIER, "NABH", NO_CODE)
    assert ambiguous["code"] is None
    assert len(description_candidates("CT scan abdomen", descriptions)) == 2
    unrelated = resolve_item({"description": "unknown unrelated item", "claimed_amount": 100},
                              rates, descriptions, TIER, "NABH", NO_CODE)
    assert unrelated["code"] is None


def test_manual_mode_waits_for_officer_even_when_a_code_is_printed():
    row = {"description": "Complete Haemogram", "billed_code": "LB012", "claimed_amount": 180}
    pending = resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", MANUAL)
    assert pending["code"] is None
    chosen = resolve_item({**row, "matched_code": "LB012"}, RATES, DESCRIPTIONS,
                          TIER, "NABH", MANUAL)
    assert chosen["code"] == "LB012" and chosen["admissible_amount"] == 180


def test_diagnosis_alone_does_not_create_a_payable_procedure():
    row = resolve_item({"description": "", "claimed_amount": 100}, RATES, DESCRIPTIONS,
                       TIER, "NABH", NO_CODE, diagnosis="anaemia")
    assert row["code"] is None and row["admissible_amount"] is None
