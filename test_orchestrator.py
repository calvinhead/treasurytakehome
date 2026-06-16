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
    assert assemble_verdict("Old Tom Distillery", "45", _fields()).verdict == "APPROVE"


def test_scenario_b_fuzzy_brand_still_approves():
    result = assemble_verdict("Stone's Throw", "45", _fields(brand="STONE'S THROW"))
    assert result.verdict == "APPROVE"


def test_scenario_c_abv_mismatch_rejects():
    # Brand and warning read correctly, so the ABV mismatch is trustworthy.
    result = assemble_verdict("Old Tom Distillery", "45", _fields(abv="40%"))
    assert result.verdict == "REJECT"


def test_scenario_d_warning_titlecase_rejects():
    bad = CANONICAL_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
    result = assemble_verdict("Old Tom Distillery", "45", _fields(warning=bad))
    assert result.verdict == "REJECT"


def test_scenario_e_warning_missing_needs_review():
    # Brand and ABV read fine; an empty warning can't be told apart from one
    # the photo simply didn't capture, so defer to a human.
    result = assemble_verdict("Old Tom Distillery", "45", _fields(warning=""))
    assert result.verdict == "NEEDS REVIEW"


def test_garbled_photo_all_fields_wrong_needs_review():
    # The real-world glare case: every field misread (nothing matches). With no
    # correct read to anchor on, this is a photo problem, not a confident reject.
    garbled = _fields(brand="Modelo", abv="5", warning="WARNING 1 GENERAL BEERS 1062")
    result = assemble_verdict("Corona Extra", "4.6", garbled)
    assert result.verdict == "NEEDS REVIEW"


def test_scenario_f_unreadable_needs_review():
    blank = _fields(brand="", abv="", warning="")
    result = assemble_verdict("Old Tom Distillery", "45", blank)
    assert result.verdict == "NEEDS REVIEW"


def test_verify_batch_and_summary():
    def fake_verify(brand, abv, image_bytes):
        from orchestrator import VerificationResult
        return VerificationResult("APPROVE" if brand == "good" else "REJECT", [], {}, "")

    from orchestrator import verify_batch, summarize
    items = [
        {"filename": "a.png", "brand": "good", "abv": "45", "image_bytes": b""},
        {"filename": "b.png", "brand": "bad", "abv": "45", "image_bytes": b""},
        {"filename": "c.png", "brand": "good", "abv": "45", "image_bytes": b""},
    ]
    summary = summarize(verify_batch(items, _verify=fake_verify))
    assert summary == {"total": 3, "APPROVE": 2, "REJECT": 1, "NEEDS REVIEW": 0}
