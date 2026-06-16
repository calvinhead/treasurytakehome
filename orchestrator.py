"""Orchestration: glue the extractor and comparison checks into one verdict.

verify_label() is the single entry point the UI calls. The verdict logic is
split into assemble_verdict(), a pure function over already-extracted fields,
so it is unit-testable without any network or model call.
"""

from dataclasses import dataclass
from typing import List

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


def _label_unreadable(fields: dict) -> bool:
    """True if the core fields all came back empty (image couldn't be read)."""
    core = ["brand_name", "abv", "government_warning"]
    return all(not (fields.get(k) or "").strip() for k in core)


def assemble_verdict(expected_brand: str, expected_abv: str, fields: dict) -> VerificationResult:
    """Pure verdict logic over already-extracted fields. No network calls.

    NEEDS REVIEW is reserved for the case where the label couldn't be read
    (scenario F): better a human looks than the tool auto-rejects a bad photo.
    A confidently-read label either APPROVES (all checks pass) or REJECTS.
    """
    if _label_unreadable(fields):
        return VerificationResult(
            verdict="NEEDS REVIEW",
            checks=[],
            extracted=fields,
            message=("Couldn't read the label clearly. Please upload a sharper, "
                     "straight-on photo with no glare."),
        )

    checks = [
        check_brand(expected_brand, fields.get("brand_name", "")),
        check_abv(expected_abv, fields.get("abv", "")),
        check_warning(fields.get("government_warning", "")),
    ]

    if all(c.passed for c in checks):
        return VerificationResult(
            verdict="APPROVE",
            checks=checks,
            extracted=fields,
            message="All required fields match the application.",
        )

    failed = [c.field for c in checks if not c.passed]
    return VerificationResult(
        verdict="REJECT",
        checks=checks,
        extracted=fields,
        message="Does not match the application: " + ", ".join(failed) + ".",
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
