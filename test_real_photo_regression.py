"""Live regression test against a real Corona Extra photo — the Task 1 fixture.

This calls the Haiku vision model, so it is a paid/live test and is skipped
unless ANTHROPIC_API_KEY is set. It is also subject to some model variance.

corona_extra_back.jpeg is a real back-label phone photo: glare, a curved glass
surface, QR/barcode clutter, and EXIF orientation 6 (the camera was rotated).
The current pipeline does not apply EXIF orientation and downsamples the whole
frame, so the model receives a SIDEWAYS, low-detail image and confidently
MISREADS it — observed: brand "Czechvar" (hallucinated; the label says Corona
Extra) and ABV "5%" (the label says 4.6%) — producing a false REJECT of a
compliant label. This is the cardinal-rule violation Task 1 targets.

The test encodes the TARGET behavior and currently FAILS. It should pass once
orientation normalization (step 2) and fixed-grid tiling (step 3) land.
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="live vision call — set ANTHROPIC_API_KEY to run",
)

from orchestrator import verify_label  # noqa: E402  (after skip guard)

FIXTURE = os.path.join(os.path.dirname(__file__), "corona_extra_back.jpeg")
# The application's expected values for this label (beer, imported from Mexico).
EXPECTED_BRAND = "Corona Extra"
EXPECTED_ABV = "4.6"


def _check(result, field):
    """Pull one FieldResult out of a VerificationResult by field name."""
    return next(c for c in result.checks if c.field == field)


def test_corona_extra_real_photo_not_confidently_misread():
    with open(FIXTURE, "rb") as f:
        result = verify_label(EXPECTED_BRAND, EXPECTED_ABV, f.read())

    brand = _check(result, "Brand name")
    abv = _check(result, "Alcohol content")

    # Cardinal rule: never infer a brand. A correct read OR an honest abstention
    # (empty) is acceptable; a confident WRONG brand (e.g. "Czechvar") is not.
    assert brand.passed or not (brand.found or "").strip(), (
        f"confident wrong brand read from the label: {brand.found!r}"
    )
    # The ABV (4.6%) is printed on this label, so it must be read, not guessed.
    assert abv.passed, f"ABV should read 4.6%, got {abv.found!r}"
    # A compliant label must not be REJECTed on fabricated values.
    assert result.verdict != "REJECT", (
        f"false REJECT of a compliant label: {result.verdict} — {result.message}"
    )
