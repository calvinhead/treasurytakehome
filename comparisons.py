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

# Brand-name similarity is scored 0-100 with rapidfuzz token_set_ratio, which
# ignores word order and extra/missing words -- so "Kirkland" vs "Kirkland
# Signature" and "Old Tom" vs "Old Tom Distillery" score 100, not a low ratio.
# Three bands:
#   >= BRAND_PASS_THRESHOLD   -> confident match          (PASS)
#   >= BRAND_REVIEW_THRESHOLD -> close but not confident   (NEEDS REVIEW)
#   below                     -> clearly a different brand (FAIL)
# 90 keeps the prior confident-match bar (clean matches sit at 100 with margin,
# while different brands that merely share a word score < 90 and go to review).
# 60 is the review floor: genuine mismatches in testing scored < 30, well below.
BRAND_PASS_THRESHOLD = 90
BRAND_REVIEW_THRESHOLD = 60

# The government warning body is compared with a high fuzzy threshold rather
# than exact equality, so a minor vision/OCR slip on a real label (one
# misread or dropped word) doesn't falsely fail a compliant warning, while
# genuinely reworded or incomplete warnings still fall below it and fail.
WARNING_MATCH_THRESHOLD = 90

# Allowed absolute difference between expected and label ABV, in percentage
# points. Absorbs trivial formatting noise (e.g. "45" vs "45.0").
ABV_TOLERANCE = 0.1


# --- Beverage-type classification + required-field matrix (Task 4) ---

# Requirement codes used by the matrix below.
REQUIRED = "required"
CONDITIONAL = "conditional"      # required only in cases we don't detect here
NOT_APPLICABLE = "n/a"

# Per-beverage-type required-field matrix - the single source of truth for which
# fields each type must carry. Tasks 5/6 extend the *verification* of these; for
# now only brand, ABV, and government warning are actually checked, and only the
# ABV requirement is wired into the verdict. The sulfites + country-of-origin
# slots are reserved (verified in Task 6).
REQUIRED_FIELDS = {
    "beer": {
        "brand_name": REQUIRED, "class_type": REQUIRED, "abv": CONDITIONAL,
        "net_contents": REQUIRED, "producer": REQUIRED,
        "government_warning": REQUIRED, "sulfites": NOT_APPLICABLE,
        "country_of_origin": CONDITIONAL,
    },
    "wine": {
        "brand_name": REQUIRED, "class_type": REQUIRED, "abv": REQUIRED,
        "net_contents": REQUIRED, "producer": REQUIRED,
        "government_warning": REQUIRED, "sulfites": CONDITIONAL,
        "country_of_origin": CONDITIONAL,
    },
    "spirits": {
        "brand_name": REQUIRED, "class_type": REQUIRED, "abv": REQUIRED,
        "net_contents": REQUIRED, "producer": REQUIRED,
        "government_warning": REQUIRED, "sulfites": CONDITIONAL,
        "country_of_origin": CONDITIONAL,
    },
}

# Whole-word keyword cues per type, matched case-insensitively. Precedence is
# spirits > wine > beer when a string somehow hits more than one set.
_SPIRITS_KW = (
    "spirit", "spirits", "whiskey", "whisky", "bourbon", "scotch", "rye",
    "vodka", "gin", "rum", "tequila", "mezcal", "brandy", "cognac", "liqueur",
    "schnapps", "proof", "distilled",
)
_WINE_KW = (
    "wine", "vino", "varietal", "cabernet", "merlot", "chardonnay", "pinot",
    "sauvignon", "riesling", "zinfandel", "syrah", "shiraz", "malbec",
    "champagne", "prosecco", "port", "sherry", "sulfite", "sulfites",
)
_BEER_KW = (
    "beer", "lager", "ale", "malt", "stout", "porter", "pilsner", "ipa",
    "cerveza", "brew",
)


def _has_keyword(text: str, keywords) -> bool:
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in keywords)


def classify_beverage(class_type: str, abv: str = "") -> str:
    """Infer {beer, wine, spirits} from the class/type the model read, plus the
    ABV text (which carries the "proof" spirits cue). Returns "unknown" when no
    rule matches - the caller must NOT guess a rule set in that case.

    Known limitation: flavored malt beverages DO require an ABV statement, but
    "flavored" isn't reliably detectable here, so anything matching the beer
    keywords is treated as beer with ABV optional. Compound terms like "barley
    wine" (a strong ale) may classify as wine; acceptable for this prototype.
    """
    text = f"{class_type} {abv}".lower()
    if _has_keyword(text, _SPIRITS_KW):
        return "spirits"
    if _has_keyword(text, _WINE_KW):
        return "wine"
    if _has_keyword(text, _BEER_KW):
        return "beer"
    return "unknown"


@dataclass
class FieldResult:
    """Outcome of verifying one field against the application."""

    field: str
    expected: str
    found: str
    passed: bool
    reason: str
    # Three-way triage outcome: "PASS" | "FAIL" | "NEEDS REVIEW". The binary
    # checks (abv, warning) leave this blank and it is derived from `passed`;
    # check_brand sets "NEEDS REVIEW" for its close-but-uncertain band.
    status: str = ""

    def __post_init__(self):
        if not self.status:
            self.status = "PASS" if self.passed else "FAIL"


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces and trim the ends."""
    return " ".join((text or "").split())


def _normalize_brand(text: str) -> str:
    """Lowercase and strip punctuation/whitespace for fuzzy brand comparison."""
    lowered = (text or "").lower()
    stripped = re.sub(r"[^a-z0-9 ]", "", lowered)
    return _normalize_whitespace(stripped)


def check_brand(expected: str, found: str) -> FieldResult:
    """Fuzzy brand-name match with a three-way result.

    Comparison is case-, punctuation-, and whitespace-insensitive, then scored
    with token_set_ratio so subset/extra-word names still match: Dave's "STONE'S
    THROW" vs "Stone's Throw", "Kirkland" vs "Kirkland Signature", and "Old Tom"
    vs "Old Tom Distillery" all score 100. A confident score PASSes, a clearly
    different name FAILs, and an in-between near-match is routed to NEEDS REVIEW
    rather than auto-rejected.
    """
    expected_norm = _normalize_brand(expected)
    found_norm = _normalize_brand(found)

    if not found_norm:
        return FieldResult(
            "Brand name", expected, found, False,
            "No brand name was read from the label.",
            status="NEEDS REVIEW",
        )

    score = fuzz.token_set_ratio(expected_norm, found_norm)

    if score >= BRAND_PASS_THRESHOLD:
        return FieldResult(
            "Brand name", expected, found, True,
            "Brand name matches the application (ignoring case and punctuation).",
        )
    if score >= BRAND_REVIEW_THRESHOLD:
        return FieldResult(
            "Brand name", expected, found, False,
            "Brand name is close but not a confident match - needs human review.",
            status="NEEDS REVIEW",
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
            status="NEEDS REVIEW",
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
            status="NEEDS REVIEW",
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

    if fuzz.ratio(found_norm.lower(), canonical_norm.lower()) < WARNING_MATCH_THRESHOLD:
        return FieldResult(
            "Government warning", CANONICAL_WARNING, found, False,
            "Warning wording does not match the required statement.",
        )

    return FieldResult(
        "Government warning", CANONICAL_WARNING, found, True,
        "Government warning is present, correctly worded, and capitalized.",
    )


# --- Presence / well-formedness checks (Tasks 5 + 6) ---
#
# These verify fields the application gives no expected value for, so they check
# PRESENCE (and light well-formedness) rather than a value match. Per the absence
# rule, an absent required field is NEEDS REVIEW, never a hard FAIL - they only
# ever return PASS or NEEDS REVIEW.

def check_present(field_label: str, value: str, what: str) -> FieldResult:
    """Generic presence check: present -> PASS, absent -> NEEDS REVIEW."""
    value = (value or "").strip()
    if not value:
        return FieldResult(field_label, "", "", False,
                           f"No {what} was read from the label.",
                           status="NEEDS REVIEW")
    return FieldResult(field_label, "", value, True,
                       f"{field_label} is present on the label.")


# A net-contents statement carries a quantity: a number directly followed by a
# volume unit. Whitespace between them is OPTIONAL ("750ml" is valid), matching
# is case-insensitive, periods are optional, and multi-part imperial like
# "1 PT 9 FL OZ" is fine - matching any one number+unit is enough. The trailing
# (?![a-z]) keeps a unit from matching inside a longer word (e.g. "ozone").
_NET_UNIT = (
    r"(?:fluid\s*ounces?|fl\.?\s*oz|ounces?|oz|"
    r"milli\s*li(?:ters?|tres?)|ml|centi\s*li(?:ters?|tres?)|cl|"
    r"li(?:ters?|tres?)|l|"
    r"gallons?|gal|pints?|pt|quarts?|qt)"
)
_NET_QTY_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*" + _NET_UNIT + r"\.?(?![a-z])", re.IGNORECASE)


def check_net_contents(value: str) -> FieldResult:
    """Presence + well-formedness for net contents (a number plus a volume
    unit). Absent or not-a-quantity -> NEEDS REVIEW; well-formed -> PASS."""
    value = (value or "").strip()
    if not value:
        return FieldResult("Net contents", "", "", False,
                           "No net contents statement was read from the label.",
                           status="NEEDS REVIEW")
    if _NET_QTY_RE.search(value):
        return FieldResult("Net contents", "", value, True,
                           "Net contents is present and well-formed.")
    return FieldResult("Net contents", "", value, False,
                       "Net contents was read but doesn't look like a quantity "
                       "- please review.", status="NEEDS REVIEW")


def check_sulfite_declaration(value: str) -> FieldResult:
    """Wine: a sulfiting-agent declaration must be present. Mentions sulfites
    -> PASS; absent -> NEEDS REVIEW."""
    value = (value or "").strip()
    if value and re.search(r"sul[fp]h?ites?", value, re.IGNORECASE):
        return FieldResult("Sulfite declaration", "", value, True,
                           "Sulfite declaration is present.")
    return FieldResult("Sulfite declaration", "", value, False,
                       "No sulfite declaration ('Contains sulfites') was found "
                       "- please review.", status="NEEDS REVIEW")


# Country names used both to detect an import and to satisfy the country-of-
# origin statement. Small, common-case list - extend as needed.
_COUNTRIES = (
    "mexico", "canada", "france", "italy", "spain", "germany", "ireland",
    "scotland", "england", "united kingdom", "japan", "china", "netherlands",
    "belgium", "australia", "new zealand", "chile", "argentina", "portugal",
    "brazil", "russia", "poland", "sweden", "czech republic", "czechia",
    "austria", "switzerland", "greece", "peru", "cuba", "jamaica",
)


def _found_country(text: str):
    low = (text or "").lower()
    for c in _COUNTRIES:
        if re.search(r"\b" + re.escape(c) + r"\b", low):
            return c
    return None


def is_import(text: str) -> bool:
    """True if the text marks an imported product - an 'imported' cue or a
    foreign country name. A bare 'product of' is not a trigger on its own
    ('Product of USA' is domestic); a foreign country name is."""
    low = (text or "").lower()
    return bool(re.search(r"\bimport", low) or _found_country(low))


def check_country_of_origin(class_type: str, producer: str,
                            country_of_origin: str = "") -> FieldResult:
    """Imports must state a country of origin. Recognizes any common origin
    phrasing - "Product of X", "Produced in X", "Imported from X", or a bare
    country name - by finding the country anywhere in the origin / class /
    producer text. Present -> PASS, absent -> NEEDS REVIEW."""
    country = _found_country(f"{country_of_origin} {class_type} {producer}")
    if country:
        return FieldResult("Country of origin", "", country.title(), True,
                           f"Country of origin is present ({country.title()}).")
    return FieldResult("Country of origin", "", "", False,
                       "Imported product, but no country of origin was found "
                       "- please review.", status="NEEDS REVIEW")
