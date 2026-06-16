"""Unit tests for the field comparison functions.

Each test maps to a scenario in the build guide's Definition of Done,
which in turn maps to a stakeholder quote from the interviews.
"""

from comparisons import check_brand, check_abv, check_warning, CANONICAL_WARNING


# --- Brand name (Dave's "STONE'S THROW" example) ---

def test_brand_exact_match_passes():
    assert check_brand("Old Tom Distillery", "Old Tom Distillery").passed


def test_brand_scenario_b_case_and_punctuation_differ_passes():
    # Scenario B: label "STONE'S THROW" vs application "Stone's Throw"
    assert check_brand("Stone's Throw", "STONE'S THROW").passed


def test_brand_clearly_different_fails():
    assert not check_brand("Old Tom Distillery", "Buffalo Trace").passed


def test_brand_missing_fails():
    assert not check_brand("Old Tom Distillery", "").passed


# --- ABV (scenario C) ---

def test_abv_match_passes_ignoring_surrounding_text():
    assert check_abv("45% Alc./Vol. (90 Proof)", "45% Alc./Vol.").passed


def test_abv_scenario_c_mismatch_fails_and_shows_both():
    # Scenario C: label 40 vs application 45
    result = check_abv("45", "40")
    assert not result.passed
    assert "45" in result.reason and "40" in result.reason


def test_abv_within_tolerance_passes():
    assert check_abv("45", "45.0").passed


# --- Government warning (scenarios D and E) ---

def test_warning_correct_passes():
    assert check_warning(CANONICAL_WARNING).passed


def test_warning_scenario_d_title_case_fails_on_capitalization():
    # Scenario D: "Government Warning" in title case
    title_case = CANONICAL_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
    result = check_warning(title_case)
    assert not result.passed
    assert "capital" in result.reason.lower()


def test_warning_scenario_e_missing_fails_as_not_found():
    # Scenario E: warning missing entirely
    result = check_warning("")
    assert not result.passed
    assert "not found" in result.reason.lower()


def test_warning_reworded_fails():
    assert not check_warning("GOVERNMENT WARNING: Drinking is bad for you.").passed


def test_warning_minor_ocr_slip_still_passes():
    # A real label read with one dropped letter should not falsely fail.
    slipped = CANONICAL_WARNING.replace("birth defects", "birth defect")
    assert check_warning(slipped).passed
