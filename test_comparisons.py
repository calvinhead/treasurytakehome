"""Unit tests for the field comparison functions.

Each test maps to a scenario in the build guide's Definition of Done,
which in turn maps to a stakeholder quote from the interviews.
"""

from comparisons import (
    check_brand, check_abv, check_warning, CANONICAL_WARNING, classify_beverage,
    check_present, check_net_contents, check_sulfite_declaration,
    check_country_of_origin,
)


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


# --- Brand name (Task 7: token_set_ratio + NEEDS REVIEW band) ---

def test_brand_kirkland_subset_matches():
    # Extra trailing word ("Signature") must not sink an otherwise-clear match.
    assert check_brand("Kirkland Signature", "KIRKLAND").passed
    assert check_brand("Kirkland", "Kirkland Signature").passed


def test_brand_old_tom_subset_matches():
    assert check_brand("Old Tom Distillery", "Old Tom").passed


def test_brand_near_match_needs_review():
    # Shares a word but is a different brand: defer to a human, don't auto-fail
    # and don't auto-pass.
    result = check_brand("Buffalo Trace", "Buffalo Bill")
    assert not result.passed
    assert result.status == "NEEDS REVIEW"


def test_brand_true_mismatch_still_fails():
    # The looser matcher must NOT make everything pass.
    result = check_brand("Corona Extra", "Dos Equis")
    assert not result.passed
    assert result.status == "FAIL"


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


# --- Beverage-type classifier (Task 4) ---

def test_classify_beer():
    assert classify_beverage("Imported Beer from Mexico") == "beer"
    assert classify_beverage("India Pale Ale") == "beer"
    assert classify_beverage("Premium Lager") == "beer"


def test_classify_spirits():
    assert classify_beverage("Kentucky Straight Bourbon Whiskey") == "spirits"
    assert classify_beverage("Tequila Blanco") == "spirits"
    # 'proof' in the ABV text is a spirits cue even when class/type is vague.
    assert classify_beverage("Premium", "40% Alc/Vol (80 Proof)") == "spirits"


def test_classify_wine():
    assert classify_beverage("Red Wine") == "wine"
    assert classify_beverage("Cabernet Sauvignon") == "wine"


def test_classify_unknown():
    assert classify_beverage("Premium Craft Beverage") == "unknown"
    assert classify_beverage("") == "unknown"


# --- Presence / well-formedness checks (Tasks 5 + 6) ---

def test_check_present():
    assert check_present("Producer", "Old Tom Distillery, KY", "producer").passed
    r = check_present("Producer", "", "producer")
    assert not r.passed and r.status == "NEEDS REVIEW"


def test_check_net_contents():
    assert check_net_contents("750 mL").passed
    assert check_net_contents("12 FL OZ").passed
    malformed = check_net_contents("not a quantity")
    assert not malformed.passed and malformed.status == "NEEDS REVIEW"
    assert check_net_contents("").status == "NEEDS REVIEW"


def test_check_net_contents_formats():
    # Spacing/case/period variants must all PASS (the Caymus "750ml" bug).
    for ok in ["750ml", "750mL", "750ML", "750 mL", "1.75 LITER", "1.75L",
               "1,75 l", "1 L", "5 cl", "750 milliliters", "12 FL OZ",
               "12 FL. OZ.", "12 fluid ounces", "1 PT 9 FL OZ", "1 gallon"]:
        assert check_net_contents(ok).passed, ok
    # Genuine junk still defers.
    for junk in ["see back", "", "n/a", "Premium", "molded into glass"]:
        assert check_net_contents(junk).status == "NEEDS REVIEW", junk


def test_check_sulfite_declaration():
    assert check_sulfite_declaration("CONTAINS SULFITES").passed
    assert check_sulfite_declaration("").status == "NEEDS REVIEW"


def test_check_country_of_origin():
    assert check_country_of_origin("Imported Beer from Mexico", "").passed
    # Origin phrasings beyond "imported from" must be recognized (Kirkland).
    assert check_country_of_origin("Tequila Blanco", "", "PRODUCT OF MEXICO").passed
    assert check_country_of_origin("Vodka", "", "Produced in France").passed
    r = check_country_of_origin("Imported Lager", "Imported by ACME, IL")
    assert not r.passed and r.status == "NEEDS REVIEW"
