"""Tests for the verdict logic, using hand-built field dicts so no model
or network call is needed. Each maps to a Definition-of-Done scenario."""

from orchestrator import assemble_verdict
from comparisons import CANONICAL_WARNING


def _fields(brand="OLD TOM DISTILLERY", abv="45% Alc./Vol.", warning=CANONICAL_WARNING,
            class_type="Kentucky Straight Bourbon Whiskey", net_contents="750 mL",
            producer="Old Tom Distillery", sulfite_declaration="",
            country_of_origin=""):
    return {
        "brand_name": brand,
        "class_type": class_type,
        "abv": abv,
        "net_contents": net_contents,
        "producer": producer,
        "government_warning": warning,
        "sulfite_declaration": sulfite_declaration,
        "country_of_origin": country_of_origin,
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


def test_near_match_brand_needs_review():
    # Brand is a close-but-uncertain match; ABV and warning read correctly. The
    # near-match must NOT force a REJECT - overall verdict is NEEDS REVIEW.
    result = assemble_verdict("Buffalo Trace", "45", _fields(brand="Buffalo Bill"))
    assert result.verdict == "NEEDS REVIEW"


def test_real_brand_mismatch_still_rejects():
    # A genuinely different brand, anchored by ABV + warning reading correctly,
    # must still REJECT - a real FAIL outranks the NEEDS REVIEW band.
    result = assemble_verdict("Corona Extra", "45", _fields(brand="Dos Equis"))
    assert result.verdict == "REJECT"


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


# --- Per-beverage-type required-field logic (Task 4) ---

def test_beer_with_abv_matches_approves():
    # Beer whose ABV statement is present and matches -> APPROVE (no regression).
    result = assemble_verdict("Corona Extra", "4.6", _fields(
        brand="Corona Extra", abv="4.6% Alc/Vol",
        class_type="Imported Beer from Mexico"))
    assert result.verdict == "APPROVE"
    assert result.beverage_type == "beer"


def test_beer_missing_abv_is_na_not_fail():
    # Standard beer with NO ABV statement: ABV is N/A, not a FAIL, and does not
    # drive a REJECT. Brand + warning reading -> APPROVE.
    result = assemble_verdict("Corona Extra", "4.6", _fields(
        brand="Corona Extra", abv="", class_type="Imported Beer from Mexico"))
    assert result.verdict == "APPROVE"
    assert result.beverage_type == "beer"
    assert all(c.field != "Alcohol content" for c in result.checks)  # excluded, not failed


def test_spirits_missing_abv_needs_review():
    # Refinement: a REQUIRED-but-MISSING ABV is "look closer" (NEEDS REVIEW),
    # not a hard REJECT - absence can't be told from an uncaptured small print.
    result = assemble_verdict("Old Tom Distillery", "45", _fields(
        abv="", class_type="Kentucky Straight Bourbon Whiskey"))
    assert result.verdict == "NEEDS REVIEW"
    assert result.beverage_type == "spirits"


def test_wine_missing_abv_needs_review():
    result = assemble_verdict("Caymus", "14.2", _fields(
        brand="Caymus", abv="", class_type="Red Wine",
        sulfite_declaration="Contains Sulfites"))
    assert result.verdict == "NEEDS REVIEW"
    assert result.beverage_type == "wine"


def test_spirits_present_wrong_abv_rejects():
    # A present ABV that conflicts with the application is a genuine mismatch.
    result = assemble_verdict("Old Tom Distillery", "45", _fields(
        abv="50% Alc/Vol", class_type="Kentucky Straight Bourbon Whiskey"))
    assert result.verdict == "REJECT"


def test_wine_present_wrong_abv_rejects():
    result = assemble_verdict("Caymus", "14.2", _fields(
        brand="Caymus", abv="13% Alc/Vol", class_type="Red Wine",
        sulfite_declaration="Contains Sulfites"))
    assert result.verdict == "REJECT"


# --- Task 5: net contents / producer presence ---

def test_missing_net_contents_needs_review():
    result = assemble_verdict("Old Tom Distillery", "45", _fields(net_contents=""))
    assert result.verdict == "NEEDS REVIEW"


def test_missing_producer_needs_review():
    result = assemble_verdict("Old Tom Distillery", "45", _fields(producer=""))
    assert result.verdict == "NEEDS REVIEW"


# --- Task 6: sulfites (wine) + country of origin (imports) ---

def test_wine_without_sulfite_needs_review():
    result = assemble_verdict("Caymus", "14.2", _fields(
        brand="Caymus", abv="14.2% Alc/Vol", class_type="Red Wine",
        sulfite_declaration=""))
    assert result.verdict == "NEEDS REVIEW"


def test_wine_with_sulfite_approves():
    result = assemble_verdict("Caymus", "14.2", _fields(
        brand="Caymus", abv="14.2% Alc/Vol", class_type="Red Wine",
        sulfite_declaration="CONTAINS SULFITES"))
    assert result.verdict == "APPROVE"
    assert result.beverage_type == "wine"


def test_imported_beer_without_country_needs_review():
    result = assemble_verdict("Some Lager", "5", _fields(
        brand="Some Lager", abv="5% Alc/Vol", class_type="Imported Lager",
        producer="Imported by ACME, Chicago, IL"))
    assert result.verdict == "NEEDS REVIEW"


def test_imported_beer_with_country_approves():
    result = assemble_verdict("Some Lager", "5", _fields(
        brand="Some Lager", abv="5% Alc/Vol",
        class_type="Imported Lager from Canada",
        producer="Brewed in Canada, imported by ACME"))
    assert result.verdict == "APPROVE"


def test_domestic_spirits_no_country_or_sulfite():
    # Domestic spirits: not an import -> no country requirement; spirits -> no
    # sulfite requirement. All present required fields -> APPROVE.
    result = assemble_verdict("Old Tom Distillery", "45", _fields(
        class_type="Kentucky Straight Bourbon Whiskey",
        producer="Old Tom Distillery, Bardstown, KY"))
    assert result.verdict == "APPROVE"
    assert result.beverage_type == "spirits"


# --- Task 3: front+back merge + back-only abstention (multi-image) ---

def test_front_plus_back_merged_fields_approve():
    # Simulates the merged result of a front+back pair: the front supplied
    # brand/class/ABV, the back supplied warning/producer/net. All required
    # fields present -> APPROVE.
    merged = _fields(brand="Old Tom Distillery", abv="45% Alc/Vol",
                     class_type="Kentucky Straight Bourbon Whiskey",
                     net_contents="750 mL", producer="Old Tom Distillery, KY")
    result = assemble_verdict("Old Tom Distillery", "45", merged)
    assert result.verdict == "APPROVE"


def test_back_only_missing_brand_still_abstains():
    # A back-only photo that can't see the (front) brand must abstain, not guess
    # - cardinal-rule behavior preserved.
    back_only = _fields(brand="", class_type="Kentucky Straight Bourbon Whiskey")
    result = assemble_verdict("Old Tom Distillery", "45", back_only)
    assert result.verdict == "NEEDS REVIEW"


def test_kirkland_product_of_mexico_country_passes():
    # "PRODUCT OF MEXICO" (not "imported ... from") must satisfy country of origin.
    result = assemble_verdict("Kirkland Signature", "40", _fields(
        brand="KIRKLAND SIGNATURE", abv="40% Alc/Vol", class_type="Tequila Blanco",
        producer="Destiladora, Jalisco", country_of_origin="PRODUCT OF MEXICO"))
    assert result.verdict == "APPROVE"
    coo = next(c for c in result.checks if c.field == "Country of origin")
    assert coo.passed


def test_verified_field_order_covers_every_checked_field():
    # The batch table columns key off VERIFIED_FIELD_ORDER; it must cover every
    # field assemble_verdict can produce, so batch can't drift from single-label.
    from orchestrator import VERIFIED_FIELD_ORDER
    seen = set()
    for f in [
        _fields(class_type="Imported Beer from Mexico"),
        _fields(class_type="Red Wine", sulfite_declaration="Contains Sulfites"),
        _fields(class_type="Kentucky Straight Bourbon Whiskey"),
        _fields(class_type="Imported Lager", abv=""),
    ]:
        for c in assemble_verdict("X", "5", f).checks:
            seen.add(c.field)
    assert seen <= set(VERIFIED_FIELD_ORDER), seen - set(VERIFIED_FIELD_ORDER)


def test_unknown_type_needs_review():
    # Class/type we can't classify -> don't guess the rule set -> NEEDS REVIEW,
    # even though brand/ABV/warning all read fine.
    result = assemble_verdict("Old Tom Distillery", "45", _fields(
        class_type="Premium Craft Beverage"))
    assert result.verdict == "NEEDS REVIEW"
    assert result.beverage_type == "unknown"


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


def test_batch_preserves_input_order_under_concurrency():
    # Earlier items finish LATER (longer sleep); output must still be input order.
    import time
    from orchestrator import verify_batch, VerificationResult

    def fake_verify(brand, abv, image_bytes):
        time.sleep(0.01 * (10 - int(brand)))   # brand "0" sleeps most, finishes last
        return VerificationResult("APPROVE", [], {}, "")

    items = [{"filename": f"{i}.png", "brand": str(i), "abv": "5", "image_bytes": b""}
             for i in range(10)]
    out = verify_batch(items, _verify=fake_verify)
    assert [o["filename"] for o in out] == [f"{i}.png" for i in range(10)]


def test_batch_retries_rate_limit_then_succeeds(monkeypatch):
    import orchestrator
    from orchestrator import verify_batch, VerificationResult
    monkeypatch.setattr(orchestrator, "_sleep", lambda *_: None)   # no real backoff

    calls = {"n": 0}

    def flaky(brand, abv, image_bytes):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("429 rate limit exceeded")   # detected as rate-limit
        return VerificationResult("APPROVE", [], {}, "")

    items = [{"filename": "a.png", "brand": "x", "abv": "5", "image_bytes": b""}]
    out = verify_batch(items, _verify=flaky)
    assert out[0]["result"].verdict == "APPROVE"
    assert calls["n"] == 2          # failed once, retried, then succeeded


def test_batch_hard_failure_isolated_to_its_row():
    from orchestrator import verify_batch, VerificationResult

    def verify(brand, abv, image_bytes):
        if brand == "boom":
            raise ValueError("kaboom")     # non-rate-limit hard error
        return VerificationResult("APPROVE", [], {}, "")

    items = [
        {"filename": "ok1.png", "brand": "x", "abv": "5", "image_bytes": b""},
        {"filename": "bad.png", "brand": "boom", "abv": "5", "image_bytes": b""},
        {"filename": "ok2.png", "brand": "y", "abv": "5", "image_bytes": b""},
    ]
    out = verify_batch(items, _verify=verify)
    verdicts = {o["filename"]: o["result"].verdict for o in out}
    assert verdicts == {"ok1.png": "APPROVE", "bad.png": "NEEDS REVIEW",
                        "ok2.png": "APPROVE"}
    assert [o["filename"] for o in out] == ["ok1.png", "bad.png", "ok2.png"]
