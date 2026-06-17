---
title: Ttb Label Verifier
emoji: 🌖
colorFrom: pink
colorTo: gray
sdk: gradio
sdk_version: 6.18.0
python_version: '3.13'
app_file: app.py
pinned: false
license: mit
short_description: label verifier
---

# TTB Label Verifier

A prototype Gradio app that checks an alcohol-beverage **label photo** against the
**expected values from its application** and returns **APPROVE / REJECT / NEEDS
REVIEW**, with a per-field breakdown so a compliance reviewer can see *why*. It
has a single-label mode and a batch mode. Built as a take-home for a TTB / U.S.
Treasury AI Engineer role.

Field extraction uses a fast vision model (Anthropic `claude-haiku-4-5`); all
verdict logic is local, pure, and unit-tested.

Live demo: https://huggingface.co/spaces/calvinhead/ttb-label-verifier

---

## Setup & run (local)

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# the extractor calls the Anthropic API; provide a key via .env or the environment
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env

python app.py        # opens http://127.0.0.1:7860
```

`app.py` reads `ANTHROPIC_API_KEY` from the environment, falling back to `.env`
(via `python-dotenv`). Dependencies: `gradio`, `anthropic`, `rapidfuzz`,
`pillow`, `python-dotenv`.

Run the tests:

```bash
pytest -q            # 59 tests
```

The suite is offline except one live regression test
(`test_real_photo_regression.py`), which calls the model on a real photo and is
**skipped automatically when `ANTHROPIC_API_KEY` is unset**.

---

## Approach & key design decisions

The system is three modules with a clean seam: **`extractor.py`** (image → fields,
the only network call), **`comparisons.py`** (pure per-field checks + the
beverage-type rules), and **`orchestrator.py`** (`assemble_verdict`, a pure
function over already-extracted fields). The UI (`app.py`) and batch mode both
call the same `verify_label` / `assemble_verdict` path, so there is no parallel
verdict logic to drift.

**Three-outcome model (APPROVE / REJECT / NEEDS REVIEW).** A binary pass/fail is
wrong for noisy real-world photos. The third outcome lets the tool *abstain*
honestly instead of emitting a confident wrong answer — the cardinal rule of
this project.

**The "anchor guard" for trustworthy rejects.** A `REJECT` requires a *present,
conflicting* value **and** at least one correct "anchor" read (brand, ABV, or
government warning) that proves the photo is legible. If nothing reads correctly,
a mismatch is untrustworthy (a garbled photo, not a wrong label) → `NEEDS
REVIEW`. The anchor is restricted to the value/format-matched fields; presence-
only fields (net contents, producer, …) prove legibility but never anchor a
reject on their own.

**Absence ≠ conflict.** Any required field that is *missing or unreadable* →
`NEEDS REVIEW` ("look closer"), never a hard fail. Only a value that is *present
and conflicts* with the application FAILs. This applies uniformly to every
required field.

**Per-beverage-type required-field matrix.** `REQUIRED_FIELDS` (in
`comparisons.py`) is the single source of truth for what each type must carry.
The beverage type is **inferred silently** from the class/type the model reads
(keyword rules, no extra model call); an unclassifiable class/type →
`unknown` → `NEEDS REVIEW` rather than applying a guessed rule set. The headline
correctness fix lives here: **ABV is required for wine and spirits but
conditional for beer** — a standard lager with no ABV statement is N/A, not a
failure. Net contents / class-type / producer are verified for presence; wine
adds a sulfite-declaration check and imports add a country-of-origin check.

**Verbatim transcription + abstention — and EXIF was the real cause.** The
prompt instructs the model to transcribe each field verbatim from visible text
and return `null` when it can't read, never inferring a brand from packaging
appearance. Investigating the real-world misreads (a Corona Extra back label
read as brand "Czechvar", ABV "5%", a confident false REJECT) showed the
dominant cause was **orientation, not resolution**: phones store a landscape
sensor frame plus an EXIF orientation flag, and the pipeline was feeding the
model a *sideways* image. Applying EXIF orientation (`ImageOps.exif_transpose`)
in the shared preprocessing path recovered the brand and ABV fully and
consistently (`Czechvar`/`5%`/REJECT → `Corona Extra`/`4.6%`/APPROVE, 3/3 live
runs).

**Fuzzy brand matching with a review band.** `check_brand` normalizes case/
punctuation/whitespace, then scores with `rapidfuzz.token_set_ratio` so
subset/extra-word names match: `Kirkland` ↔ `Kirkland Signature` and `Old Tom` ↔
`Old Tom Distillery` score 100. Three bands: **≥ 90 → PASS, 60–89 → NEEDS
REVIEW, < 60 → FAIL** — a near-match goes to a human, not a hard reject.

**Front + back, in one request.** The single-label tab accepts an optional
second photo (mandatory fine print is often on the back; the brand on the
front). Both images go to the model in **one** request and it reads each field
from whichever photo shows it. No tiling — these are two real photos.

**Batch with bounded concurrency.** Batch verifies many labels (filename →
brand/abv via CSV) through the *same* per-label path, with a worker pool capped
at `BATCH_CONCURRENCY = 5`. Results are returned in input/CSV order regardless of
completion order; a 429/rate-limit retries with bounded exponential backoff then
degrades that row to `NEEDS REVIEW`; a per-row `try/except` means one bad row
never halts the run; a `gr.Progress` bar reports completion. This cuts ~250
labels from ~16.7 min (sequential) to ~3.3 min.

**Government warning is format-strict.** Exact statutory wording + the
`GOVERNMENT WARNING` heading in all caps, compared with a high fuzzy threshold so
a single OCR slip doesn't fail a compliant warning while reworded/incomplete
text still fails.

---

## What was deliberately NOT built, and why

**Image tiling (the spec's original Task 1) — deferred, not shipped.** This was
the highest-priority spec item, and the investigation changed the conclusion:

- "Send full resolution" is a no-op on the in-use Haiku model — the API caps
  every image at ~1568 px / ~1568 visual tokens (≈ 952×1270 for a 3:4 frame), so
  a full-res photo and a downscaled one reach the model identically. Only
  region-cropping/tiling can raise effective resolution.
- But the real misreads were driven by **orientation**, not pixel count (see
  above). A clean high-res synthetic label never reproduced a resolution failure
  (Haiku reads crisp ~8 px text after downscaling), and the one residual weak
  field (a producer importer line) was legible at model resolution — a
  transcription-completeness issue fixed by prompt hardening, not pixel
  starvation.
- Fixed-grid tiling would roughly **4× the image tokens and latency per request
  for no measurable accuracy gain** on any field we could observe, and would eat
  into the ~5 s latency budget across 200–300-label batches.

Decision: ship EXIF orientation (the actual fix) and prompt hardening; revisit
tiling only against a fixture that genuinely fails on resolution *after*
orientation is correct. (Also recorded in `TTB_VERIFIER_BUILD_SPEC.md`.)

Also intentionally out of scope:

- **Automatic deskew** of residual small tilt — the available heuristic
  (projection-profile, no OpenCV) locked onto glare bands and rotated *straight*
  labels crooked. Shipping it would degrade exactly the glare photos we target.
- **Flavored-malt ABV detection** — flavored malt beverages *do* require ABV, but
  "flavored" isn't reliably detectable, so all beer is treated as ABV-optional.
- **Spirits sulfite enforcement** — CFR requires it at ≥ 10 ppm, which isn't on
  the label; the sulfite check is wired for wine only.
- **Local/offline inference fallback** — extraction depends on the Anthropic
  cloud API (documented network risk below).

---

## Testing

`pytest -q` → **59 tests, 0 failures.** Almost all are pure and offline:
`comparisons.py` field rules and the classifier, and `orchestrator.py` verdict
logic over hand-built field dicts (so no model/network is needed). Two
`test_extractor.py` tests use a fake client to assert the multi-image request
shape. One test is a **live** regression against a real photo.

**Honest fixture coverage.** Of the labels discussed in the build history, only
**Corona Extra is verified end-to-end with a real photo and a live model call**
(`corona_extra_back.jpeg`) — it exercises EXIF-orientation recovery,
anti-hallucination, all field checks, and country derivation. The others —
**Miller Lite, Kirkland, Caymus, On The Rocks — are validated as *simulated*
field sets**, not from their own photos (we don't have those images). That is a
real gap, and it's stated plainly: the *fixes* those labels rely on are each
either unit-tested (brand matching, country recognition, net-contents
well-formedness, beverage-type logic, verdict precedence) or proven live on
Corona (orientation, abstention, extraction) — but extraction from those
specific photos is not re-proven. `scenario_g_highres_fullbottle.png` is a
synthetic **negative control** (it demonstrates clean downsampling alone does
*not* break the read), not a real label.

---

## Limitations & assumptions

1. **Tiling deferred** (see above) — no remediation for a genuinely
   pixel-starved photo once orientation is correct.
2. **Flavored malt beverages** missing an ABV statement are not caught (beer is
   ABV-optional; "flavored" isn't detected).
3. **RTD / cider / sake / hard seltzer → `unknown` → `NEEDS REVIEW` by design** —
   these are genuinely ambiguous under TTB; the classifier abstains rather than
   guess. (On The Rocks is this case.)
4. **Spirits sulfite condition unenforced** (≥ 10 ppm isn't on the label).
5. **Bold text is not verifiable** from OCR — the warning check enforces exact
   wording + ALL-CAPS heading, but cannot confirm the statutory bold.
6. **Cloud-API dependency** — extraction calls Anthropic Haiku; the agency
   firewall may block it and there is **no local fallback**. Single-label
   latency is ~2–4 s/label (within the ~5 s bar).
7. **Batch is one-image-per-row** — front+back is single-label only.
8. **Batch concurrency cap = 5** (`BATCH_CONCURRENCY`, tunable) — bounded to
   avoid rate limits.
9. **Production 429 path** — `verify_label` catches exceptions internally, so in
   production a 429 is first retried by the Anthropic SDK's own backoff and then
   degraded to `NEEDS REVIEW`; the batch-level retry layer engages on any
   rate-limit that *propagates* from the verify callable (what the test
   exercises). Fully driving production 429s through the batch retry would need
   `verify_label` to propagate a typed error, or an SDK `max_retries` bump.
10. **Country-of-origin uses a small country list** (`_COUNTRIES`) — common
    cases only; extend as needed.
11. **Fixture coverage** — only one real photo (Corona); other labels are
    simulated (see Testing).
12. **Prototype scope** — no PII storage, no document retention, no COLA
    integration.

---

## Future work

- Add **real photo fixtures** for Miller Lite (rotated), Kirkland (front + back),
  Caymus, and an OTR back-of-can, and promote the simulated cases to live
  regression tests.
- A **local/offline extraction fallback** for the firewalled-network scenario.
- **Flavored-malt detection** so the conditional-ABV rule can tighten.
- **Paired (front+back) upload in batch**, and a CSV column for the second image.
- Let `verify_label` surface a typed rate-limit error so the **batch retry fully
  drives production 429s**.
- Broaden the country list / origin-phrase recognition.
- Revisit **tiling** only if a real photo fails on resolution after orientation
  is correct.
