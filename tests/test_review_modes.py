from review_logic import AUTOMATIC, CODE_ONLY, resolve_item


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
    assert row["match_source"] == "Printed code"


def test_claim_above_cghs_cap_is_limited():
    row = resolve_item({"description": "Complete Haemogram", "billed_code": "LB012",
                        "claimed_amount": 500}, RATES, DESCRIPTIONS, TIER, "NABH")
    assert row["admissible_amount"] == 300


def test_code_only_omits_uncoded_entry():
    row = {"description": "Complete Haemogram", "claimed_amount": 180}
    assert resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", CODE_ONLY) is None
    inferred = resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", AUTOMATIC)
    assert inferred["code"] == "LB012"
    assert inferred["match_source"] == "Description inferred — review"


def test_unknown_printed_code_cannot_become_calculation_code():
    row = {"description": "Unrelated service", "billed_code": "ZZ999", "claimed_amount": 100}
    assert resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", CODE_ONLY) is None
    assert resolve_item(row, RATES, DESCRIPTIONS, TIER, "NABH", AUTOMATIC)["code"] is None
