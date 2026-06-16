"""Field-level verification logic for TTB label checking.

Pure functions with no UI, network, or model dependencies, so every rule
here is directly unit-testable. Each function takes the value expected from
the application and the value read from the label image, and returns a
FieldResult describing the verdict in plain English.
"""

from dataclasses import dataclass
import re

from rapidfuzz import fuzz


# The statutory Government Warning required on alcohol beverages >= 0.5% ABV
# (Alcoholic Beverage Labeling Act of 1988; 27 CFR Part 16). This is
# public-domain U.S. law, safe to hardcode as the comparison target.
CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health "
    "problems."
)

# Brand names at or above this similarity score (0-100) are treated as a
# match. Tuned so case/punctuation differences pass while genuinely
# different names fail.
BRAND_MATCH_THRESHOLD = 90

# Allowed absolute difference between expected and label ABV, in percentage
# points. Absorbs trivial formatting noise (e.g. "45" vs "45.0").
ABV_TOLERANCE = 0.1


@dataclass
class FieldResult:
    """Outcome of verifying one field against the application."""

    field: str
    expected: str
    found: str
    passed: bool
    reason: str


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces and trim the ends."""
    return " ".join((text or "").split())


def _normalize_brand(text: str) -> str:
    """Lowercase and strip punctuation/whitespace for fuzzy brand comparison."""
    lowered = (text or "").lower()
    stripped = re.sub(r"[^a-z0-9 ]", "", lowered)
    return _normalize_whitespace(stripped)


def check_brand(expected: str, found: str) -> FieldResult:
    """Fuzzy brand-name match: case-, punctuation-, and whitespace-tolerant.

    Dave's example -- label "STONE'S THROW" vs application "Stone's Throw"
    -- must pass, so we compare normalized forms with a fuzzy ratio rather
    than requiring string equality.
    """
    expected_norm = _normalize_brand(expected)
    found_norm = _normalize_brand(found)

    if not found_norm:
        return FieldResult(
            "Brand name", expected, found, False,
            "No brand name was read from the label.",
        )

    score = fuzz.ratio(expected_norm, found_norm)
    if score >= BRAND_MATCH_THRESHOLD:
        return FieldResult(
            "Brand name", expected, found, True,
            "Brand name matches the application (ignoring case and punctuation).",
        )
    return FieldResult(
        "Brand name", expected, found, False,
        "Brand name on the label does not match the application.",
    )


def _parse_abv(text: str):
    """Pull the first numeric percentage out of an ABV string, or None."""
    match = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return float(match.group(1)) if match else None


def check_abv(expected: str, found: str) -> FieldResult:
    """Numeric ABV comparison with a small tolerance.

    Compares the numbers, not the surrounding text, so "45% Alc./Vol.
    (90 Proof)" and "45" are treated the same. Scenario C (label 40 vs
    application 45) must fail with both values shown.
    """
    expected_val = _parse_abv(expected)
    found_val = _parse_abv(found)

    if found_val is None:
        return FieldResult(
            "Alcohol content", expected, found, False,
            "No alcohol content was read from the label.",
        )
    if expected_val is None:
        return FieldResult(
            "Alcohol content", expected, found, False,
            "No expected alcohol content was provided to compare against.",
        )

    if abs(expected_val - found_val) <= ABV_TOLERANCE:
        return FieldResult(
            "Alcohol content", expected, found, True,
            f"Alcohol content matches ({found_val:g}%).",
        )
    return FieldResult(
        "Alcohol content", expected, found, False,
        f"Alcohol content differs: application says {expected_val:g}%, "
        f"label shows {found_val:g}%.",
    )


def check_warning(found: str) -> FieldResult:
    """Verify the Government Warning's wording and capitalization.

    Two separate checks, per 27 CFR Part 16:
      - the heading "GOVERNMENT WARNING" must appear in all capitals
        (Jenny's title-case rejection), and
      - the full statement must match the statutory wording.
    A missing warning fails as "not found" (scenario E); a title-case
    heading fails on capitalization (scenario D).

    Note: OCR/vision text loses font weight, so bold is not verified here;
    that limitation is documented in the README.
    """
    found_norm = _normalize_whitespace(found)
    canonical_norm = _normalize_whitespace(CANONICAL_WARNING)

    if not found_norm:
        return FieldResult(
            "Government warning", CANONICAL_WARNING, found, False,
            "Government warning was not found on the label.",
        )

    if "GOVERNMENT WARNING" not in found_norm:
        if "government warning" in found_norm.lower():
            return FieldResult(
                "Government warning", CANONICAL_WARNING, found, False,
                "'GOVERNMENT WARNING' must appear in all capital letters.",
            )
        return FieldResult(
            "Government warning", CANONICAL_WARNING, found, False,
            "The required 'GOVERNMENT WARNING' heading was not found.",
        )

    if found_norm.lower() != canonical_norm.lower():
        return FieldResult(
            "Government warning", CANONICAL_WARNING, found, False,
            "Warning wording does not match the required statement.",
        )

    return FieldResult(
        "Government warning", CANONICAL_WARNING, found, True,
        "Government warning is present, correctly worded, and capitalized.",
    )
