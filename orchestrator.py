"""Orchestration: glue the extractor and comparison checks into one verdict.

verify_label() is the single entry point the UI calls. The verdict logic is
split into assemble_verdict(), a pure function over already-extracted fields,
so it is unit-testable without any network or model call.
"""

from dataclasses import dataclass
from typing import Callable, List
from collections import Counter

from comparisons import FieldResult, check_brand, check_abv, check_warning
from extractor import extract_fields, FIELDS

# Fields read and shown to the agent, but not pass/fail verified. Adding a
# verified field later is a one-line change in assemble_verdict().
DISPLAY_ONLY = ["class_type", "net_contents", "producer"]


@dataclass
class VerificationResult:
    verdict: str                 # "APPROVE" | "NEEDS REVIEW" | "REJECT"
    checks: List[FieldResult]    # the verified fields (brand, abv, warning)
    extracted: dict              # every field read from the label
    message: str = ""            # plain-English summary or error note


def assemble_verdict(expected_brand: str, expected_abv: str, fields: dict) -> VerificationResult:
    """Pure verdict logic over already-extracted fields. No network calls.

    The key distinction: a required field that was *read but failed* is a
    confident mismatch and drives a REJECT. A required field that came back
    *empty* couldn't be verified - we can't tell "missing from the label" from
    "the photo didn't capture it" - so it drives NEEDS REVIEW, deferring to a
    human rather than auto-rejecting a possibly-compliant label.
    """
    brand_read = (fields.get("brand_name") or "").strip()
    abv_read = (fields.get("abv") or "").strip()
    warning_read = (fields.get("government_warning") or "").strip()

    # Nothing readable at all -> the photo itself is the problem.
    if not (brand_read or abv_read or warning_read):
        return VerificationResult(
            verdict="NEEDS REVIEW",
            checks=[],
            extracted=fields,
            message=("Couldn't read the label clearly. Please upload a sharper, "
                     "straight-on photo with no glare."),
        )

    checks = [
        check_brand(expected_brand, brand_read),
        check_abv(expected_abv, abv_read),
        check_warning(warning_read),
    ]
    was_read = {
        "Brand name": bool(brand_read),
        "Alcohol content": bool(abv_read),
        "Government warning": bool(warning_read),
    }

    confident_failures = [c.field for c in checks if not c.passed and was_read[c.field]]
    unread = [c.field for c in checks if not was_read[c.field]]

    if confident_failures:
        return VerificationResult(
            verdict="REJECT",
            checks=checks,
            extracted=fields,
            message="Does not match the application: " + ", ".join(confident_failures) + ".",
        )

    if unread:
        return VerificationResult(
            verdict="NEEDS REVIEW",
            checks=checks,
            extracted=fields,
            message="Couldn't clearly read: " + ", ".join(unread) +
                    ". Please review manually or upload a clearer photo.",
        )

    return VerificationResult(
        verdict="APPROVE",
        checks=checks,
        extracted=fields,
        message="All required fields match the application.",
    )


def verify_label(expected_brand: str, expected_abv: str, image_bytes: bytes) -> VerificationResult:
    """Full pipeline: extract fields from the image, then assemble a verdict."""
    try:
        fields = extract_fields(image_bytes)
    except Exception:
        return VerificationResult(
            verdict="NEEDS REVIEW",
            checks=[],
            extracted={f: "" for f in FIELDS},
            message=("The label could not be processed. Please try again with a "
                     "clearer image."),
        )
    return assemble_verdict(expected_brand, expected_abv, fields)


def verify_batch(items: List[dict], _verify: Callable = verify_label) -> List[dict]:
    """Run verification over many labels at once.

    Each item is a dict with keys: filename, brand, abv, image_bytes. Returns
    one dict per item: {"filename", "result"}. This simply loops the proven
    single-label pipeline, which is why batch adds almost no new risk. _verify
    is injectable so the loop can be tested without any network call.
    """
    out = []
    for item in items:
        result = _verify(item["brand"], item["abv"], item["image_bytes"])
        out.append({"filename": item["filename"], "result": result})
    return out


def summarize(batch_results: List[dict]) -> dict:
    """Count verdicts across a batch. Pure function over assembled results."""
    counts = Counter(b["result"].verdict for b in batch_results)
    return {
        "total": len(batch_results),
        "APPROVE": counts.get("APPROVE", 0),
        "REJECT": counts.get("REJECT", 0),
        "NEEDS REVIEW": counts.get("NEEDS REVIEW", 0),
    }
