"""Tests for the verdict logic, using hand-built field dicts so no model
or network call is needed. Each maps to a Definition-of-Done scenario."""

from orchestrator import assemble_verdict
from comparisons import CANONICAL_WARNING


def _fields(brand="OLD TOM DISTILLERY", abv="45% Alc./Vol.", warning=CANONICAL_WARNING):
    return {
        "brand_name": brand,
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "abv": abv,
        "net_contents": "750 mL",
        "producer": "Old Tom Distillery",
        "government_warning": warning,
    }


def test_scenario_a_all_match_approves():
    result = assemble_verdict("Old Tom Distillery", "45", _fields())
    assert result.verdict == "APPROVE"


def test_scenario_b_fuzzy_brand_still_approves():
    result = assemble_verdict("Stone's Throw", "45", _fields(brand="STONE'S THROW"))
    assert result.verdict == "APPROVE"


def test_scenario_c_abv_mismatch_rejects():
    result = assemble_verdict("Old Tom Distillery", "45", _fields(abv="40%"))
    assert result.verdict == "REJECT"


def test_scenario_d_warning_title_case_rejects():
    bad = CANONICAL_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
    result = assemble_verdict("Old Tom Distillery", "45", _fields(warning=bad))
    assert result.verdict == "REJECT"


def test_scenario_f_unreadable_needs_review():
    blank = _fields(brand="", abv="", warning="")
    result = assemble_verdict("Old Tom Distillery", "45", blank)
    assert result.verdict == "NEEDS REVIEW"
