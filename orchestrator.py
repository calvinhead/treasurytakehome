"""Orchestration: glue the extractor and comparison checks into one verdict.

verify_label() is the single entry point the UI calls. The verdict logic is
split into assemble_verdict(), a pure function over already-extracted fields,
so it is unit-testable without any network or model call.
"""

import time
from dataclasses import dataclass
from typing import Callable, List
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from comparisons import (
    FieldResult, check_brand, check_abv, check_warning,
    check_present, check_net_contents, check_sulfite_declaration,
    check_country_of_origin, is_import,
    classify_beverage, REQUIRED_FIELDS, REQUIRED,
)
from extractor import extract_fields, FIELDS

# Every extracted field is now verified in assemble_verdict (Tasks 5/6), so
# there is nothing left to show in a separate "read but not checked" block.
DISPLAY_ONLY = []

# Canonical display order of every field assemble_verdict can verify. The batch
# renderer keys its columns off this (single-label renders result.checks
# directly), so the two views can't drift in which fields they surface. Keep in
# sync when a verified field is added.
VERIFIED_FIELD_ORDER = [
    "Brand name", "Class/type", "Alcohol content", "Net contents",
    "Producer", "Government warning", "Sulfite declaration", "Country of origin",
]


@dataclass
class VerificationResult:
    verdict: str                 # "APPROVE" | "NEEDS REVIEW" | "REJECT"
    checks: List[FieldResult]    # the verified fields (brand, abv, warning)
    extracted: dict              # every field read from the label
    message: str = ""            # plain-English summary or error note
    beverage_type: str = ""      # inferred type driving the rule set (read-only)


# A trustworthy REJECT must be anchored by one of these value/format checks
# passing - they confirm the read is accurate, not merely that text is present.
# Presence-only checks (class/type, net contents, producer, ...) prove the photo
# is legible but never anchor a REJECT on their own.
ANCHOR_FIELDS = {"Brand name", "Alcohol content", "Government warning"}


def _verdict_from_checks(checks, fields, bev_type) -> VerificationResult:
    """Collapse the per-field checks into one verdict. Precedence: a real,
    anchored conflict -> REJECT; conflicts with no anchor -> NEEDS REVIEW
    (garbled); only absences/near-matches -> NEEDS REVIEW; all pass -> APPROVE."""
    anchor_passes = [c for c in checks if c.passed and c.field in ANCHOR_FIELDS]
    confident_failures = [c.field for c in checks if c.status == "FAIL"]
    reviews = [c.field for c in checks if c.status == "NEEDS REVIEW"]

    if all(c.passed for c in checks):
        return VerificationResult(
            verdict="APPROVE", checks=checks, extracted=fields,
            message="All required fields match the application.",
            beverage_type=bev_type)

    # A present-and-conflicting value - trustworthy only when anchored by a
    # correct read (proving the photo is legible and the read accurate).
    if confident_failures and anchor_passes:
        return VerificationResult(
            verdict="REJECT", checks=checks, extracted=fields,
            message="Does not match the application: " + ", ".join(confident_failures) + ".",
            beverage_type=bev_type)

    # Conflicts but nothing trustworthy to anchor them: can't tell a real
    # mismatch from a garbled read -> photo-quality problem.
    if confident_failures:
        return VerificationResult(
            verdict="NEEDS REVIEW", checks=checks, extracted=fields,
            message=("Couldn't read the label reliably. Please upload a sharper, "
                     "straight-on photo with no glare."),
            beverage_type=bev_type)

    # No hard conflict - only absent / near-match / malformed required fields.
    return VerificationResult(
        verdict="NEEDS REVIEW", checks=checks, extracted=fields,
        message="Please review manually: " + ", ".join(reviews) +
                ". See the per-field details below.",
        beverage_type=bev_type)


def assemble_verdict(expected_brand: str, expected_abv: str, fields: dict) -> VerificationResult:
    """Pure verdict logic over already-extracted fields. No network calls.

    The beverage type is inferred from the class/type the model read and drives
    which fields are required (see REQUIRED_FIELDS). Outcomes:
      - APPROVE: every required field for the type read and passed.
      - REJECT: a present-and-conflicting value (wrong brand/ABV, mis-worded
        warning) anchored by a correct read - the good read makes it trustworthy.
      - NEEDS REVIEW: any required field absent/abstained, a near-match brand, a
        malformed presence field, an unknown beverage type, or nothing read at
        all. Absence = "look closer", never a hard fail.

    Required-but-MISSING is always NEEDS REVIEW; only a present, conflicting value
    FAILs. ABV is type-conditional (required for wine/spirits, optional for beer
    - flavored malt beverages need it, but "flavored" isn't detected here). Net
    contents / class-type / producer are verified for presence (Task 5); wine
    adds a sulfite-declaration check and imports a country-of-origin check
    (Task 6).
    """
    brand_read = (fields.get("brand_name") or "").strip()
    abv_read = (fields.get("abv") or "").strip()
    warning_read = (fields.get("government_warning") or "").strip()
    class_read = (fields.get("class_type") or "").strip()
    net_read = (fields.get("net_contents") or "").strip()
    producer_read = (fields.get("producer") or "").strip()
    sulfite_read = (fields.get("sulfite_declaration") or "").strip()
    country_read = (fields.get("country_of_origin") or "").strip()

    bev_type = classify_beverage(class_read, abv_read)

    # Unknown beverage type: we can't pick a rule set (is ABV required? sulfites?)
    # so don't render a confident verdict - defer to a human.
    if bev_type == "unknown":
        return VerificationResult(
            verdict="NEEDS REVIEW",
            checks=[check_brand(expected_brand, brand_read),
                    check_warning(warning_read)],
            extracted=fields,
            message=("Couldn't determine the beverage type from the class/type, "
                     "so the required-field rules can't be applied confidently. "
                     "Please review manually."),
            beverage_type=bev_type)

    # Required for every type, in label order. ABV is the type-conditional one.
    checks = [
        check_brand(expected_brand, brand_read),
        check_present("Class/type", class_read, "class or type designation"),
    ]
    if abv_read:
        checks.append(check_abv(expected_abv, abv_read))          # present -> verify
    elif REQUIRED_FIELDS[bev_type]["abv"] == REQUIRED:
        # Wine/spirits: ABV is required, but absent = look closer, not a hard fail.
        checks.append(FieldResult(
            "Alcohol content", expected_abv, "", False,
            f"Alcohol content is required for {bev_type} but was not found "
            "- please review.", status="NEEDS REVIEW"))
    # else: beer (conditional) -> ABV is N/A, excluded from the verdict.
    checks.append(check_net_contents(net_read))
    checks.append(check_present("Producer", producer_read, "producer name/address"))
    checks.append(check_warning(warning_read))

    # Wine: a sulfite declaration is required. (Spirits' conditional >=10ppm
    # requirement isn't detectable from the label, so it's left unenforced.)
    if bev_type == "wine":
        checks.append(check_sulfite_declaration(sulfite_read))

    # Imports (any type): a country-of-origin statement is required.
    if is_import(f"{class_read} {producer_read} {country_read}"):
        checks.append(check_country_of_origin(class_read, producer_read, country_read))

    return _verdict_from_checks(checks, fields, bev_type)


def verify_label(expected_brand: str, expected_abv: str, image_bytes) -> VerificationResult:
    """Full pipeline: extract fields from the image(s), then assemble a verdict.

    image_bytes is one image's bytes, or a list of images (e.g. front + back of
    the same product) that are read together into one merged field set.
    """
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


# --- Batch scheduling: bounded concurrency + per-row resilience --------------
# verify_label / assemble_verdict are untouched; only the scheduling around the
# loop changes, so every successful row's verdict is identical to single-label.

BATCH_CONCURRENCY = 5        # parallel workers - bounded, easy to tune
BATCH_MAX_RETRIES = 3        # per-row retries on an API rate-limit (429)
BATCH_BACKOFF_BASE = 0.5     # seconds; exponential: 0.5, 1.0, 2.0, ...

_sleep = time.sleep          # indirection so tests can stub the backoff


def _is_rate_limit(exc: Exception) -> bool:
    """Recognize an API rate-limit / 429 without importing the SDK error type."""
    return (
        "ratelimit" in type(exc).__name__.lower()
        or getattr(exc, "status_code", None) == 429
        or "rate limit" in str(exc).lower()
    )


def _batch_error_result() -> VerificationResult:
    """Degrade-to-NEEDS-REVIEW result for a row that can't be processed -
    mirrors verify_label's own per-row error guard."""
    return VerificationResult(
        verdict="NEEDS REVIEW", checks=[], extracted={f: "" for f in FIELDS},
        message=("The label could not be processed (the service was busy). "
                 "Please re-run this row."))


def _verify_row(item: dict, _verify: Callable) -> VerificationResult:
    """Run one row through the shared verify path, retrying a rate-limit with
    bounded exponential backoff, then degrading to NEEDS REVIEW. The try/except
    guarantees one bad row never propagates and halts the batch."""
    for attempt in range(BATCH_MAX_RETRIES + 1):
        try:
            return _verify(item["brand"], item["abv"], item["image_bytes"])
        except Exception as exc:                      # isolate the row
            if _is_rate_limit(exc) and attempt < BATCH_MAX_RETRIES:
                _sleep(BATCH_BACKOFF_BASE * (2 ** attempt))
                continue
            return _batch_error_result()


def verify_batch(items: List[dict], _verify: Callable = verify_label,
                 progress=None) -> List[dict]:
    """Verify many labels with BOUNDED concurrency (BATCH_CONCURRENCY workers).

    Each item is a dict with keys: filename, brand, abv, image_bytes. Returns one
    dict per item: {"filename", "result"}, in input (CSV) ORDER regardless of
    completion order. Every row calls the same shared verify path; rate limits
    retry with backoff and a failing row degrades to NEEDS REVIEW - one bad row
    never halts the run. `progress`, if given, is called progress(fraction,
    desc=...) as rows complete. `_verify` is injectable for network-free tests.
    """
    total = len(items)
    results: List = [None] * total
    if progress is not None:
        progress(0.0, desc=f"0/{total} labels")

    with ThreadPoolExecutor(max_workers=BATCH_CONCURRENCY) as ex:
        future_to_idx = {
            ex.submit(_verify_row, item, _verify): i
            for i, item in enumerate(items)
        }
        done = 0
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            results[idx] = {"filename": items[idx]["filename"],
                            "result": fut.result()}
            done += 1
            if progress is not None:
                progress(done / total, desc=f"{done}/{total} labels")

    return results


def summarize(batch_results: List[dict]) -> dict:
    """Count verdicts across a batch. Pure function over assembled results."""
    counts = Counter(b["result"].verdict for b in batch_results)
    return {
        "total": len(batch_results),
        "APPROVE": counts.get("APPROVE", 0),
        "REJECT": counts.get("REJECT", 0),
        "NEEDS REVIEW": counts.get("NEEDS REVIEW", 0),
    }
