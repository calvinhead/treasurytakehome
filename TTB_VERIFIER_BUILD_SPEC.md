# TTB Label Verifier — Build Spec & Change Requirements

**How to use this doc (read first).** This is a change spec for an existing Gradio app (`ttb-label-verifier`) that checks an alcohol-beverage label photo against an application's expected values. It was written from the outside (screenshots \+ stakeholder brief), so **do not assume implementation details**. For each task: (1) read the relevant source first, (2) confirm the described behavior actually exists, (3) implement, (4) verify against the regression fixtures at the bottom. Implement in the **suggested task order** (correctness-payoff first). Language: **Python** (the app is Gradio).

---

## 1\. Project context

The app has a single-label mode and a batch mode. For a single label, the user enters expected values from the application (currently **brand name** and **alcohol content / ABV**), uploads a label photo, and clicks **Verify**. The app returns **APPROVE** (all required fields match), **REJECT** (a required field mismatches), or **NEEDS REVIEW** (couldn't read reliably).

**Currently verified fields:** brand name, alcohol content, government warning. **Currently extracted but NOT verified:** class/type, net contents, producer, country of origin (these appear under an "Other details read from the label (not verified)" block).

---

## 2\. Diagnosis — what's actually wrong (the *why*)

1. **Confident misreads, not read failures.** Real-world tests returned the *wrong* brand from the same category: two Corona shots read "Oro" / "Dos Equis", an OTR can read "Frankie Noir". A text-extraction step that can't read returns blank/garbled output — it does not return a plausible wrong brand. This is the model **recognizing/guessing from packaging appearance** rather than transcribing text. Root causes: (a) the image is likely downsampled before inference so fine print is gone, and (b) the prompt likely invites identification instead of verbatim transcription \+ abstention.  
2. **One-size-fits-all required fields.** ABV is being treated as mandatory for every product. It is **not required for standard beer** (see matrix), so plain lagers (Miller Lite, Corona) are FAILing on "no alcohol content found" when that is not a violation.  
3. **Mandatory fields go unverified.** Net contents (mandatory for all types), class/type, producer name/address, country of origin (imports), and wine sulfite declarations are extracted-only or ignored.  
4. **Brittle brand matching.** Exact string equality rejects obvious matches — "Kirkland Signature" vs "KIRKLAND" was REJECTed; same class of problem as "STONE'S THROW" vs "Stone's Throw".  
5. **Government warning check may be presence-only**, not format-strict (the rule is the strictest on the label).

---

## 3\. Required-field matrix (apply per beverage type)

`R` \= required · `C` \= conditional (see note) · `—` \= not required by TTB

| Field | Beer / malt | Wine | Distilled spirits | Notes |
| :---- | :---- | :---- | :---- | :---- |
| Brand name | R | R | R | Same field of vision w/ ABV \+ class for spirits |
| Class / type designation | R | R | R | e.g. "Lager", "Red Wine", "Tequila Blanco" |
| Alcohol content (ABV) | **C** | R | R | **Beer: only required for flavored malt beverages** (alcohol from added flavors/nonbeverage ingredients). Wine/spirits: always. |
| Net contents | R | R | R | May be molded/embossed into the container for beer |
| Name & address (producer/bottler/importer) | R | R | R |  |
| Country of origin | **C** | **C** | **C** | Required if **imported** (per CBP rules) |
| Government health warning | R | R | R | Required on anything ≥0.5% ABV |
| Sulfite declaration | — | **C** | **C** | Wine/spirits: required if ≥10 ppm sulfites ("Contains sulfites") |

**Implication:** the verifier must branch on beverage type. Add a beverage-type input to the application form (beer / wine / spirits), or infer it from the class/type read off the label and confirm with the user.

---

## 4\. Tasks

### Task 1 — Stop downsampling the image before inference (highest priority)

- **Audit:** find every point where the uploaded image is resized/re-encoded before it reaches the vision model. Check the Gradio `Image` component config (`type=`, any `height`/`width`), and any PIL/`cv2` resize in the preprocessing path. Log the actual pixel dimensions reaching the model.  
- **Change:** send full resolution, OR crop high-detail regions and process each (tiling). Do not shrink a full-bottle photo to a small max dimension — 1–2 mm label text vanishes and the model guesses.  
- **Acceptance:** on a straight-on Caymus/Corona photo, the small ABV and the warning text are transcribed correctly (verify via Task 5/fixtures).
- **Build status (2026-06-17): tiling DEFERRED — not shipped.** Two evidence-backed corrections to this task's premise. (1) "Send full resolution" is a no-op on the in-use Haiku 4.5 model: the API caps every image at ~1568 px / ~1568 visual tokens (≈952×1270 for a 3:4 frame), so a full-res photo and a ~1.5k-token downscale reach the model identically — only region-cropping/tiling can raise effective resolution. (2) The real-world misreads were driven mainly by **orientation**, not pixel count: applying EXIF orientation (the actual fix, now shipped) recovered the Corona back-label read fully and consistently — `Czechvar` / `5%` / REJECT → `Corona Extra` / `4.6%` / APPROVE across 3/3 runs. A clean high-res synthetic never reproduced a resolution failure (Haiku reads crisp ~8 px text after downscale), and the one residual weak field (the producer importer line) is legible at model resolution — a transcription-completeness issue fixed by prompt hardening, not pixel-starvation. Fixed-grid tiling would ~4× image tokens per request for no measurable accuracy gain on any field we can observe; it also costs latency against the ~5 s bar and multiplies across 200–300-label batches. Revisit only against a fixture that genuinely fails on resolution *after* orientation is correct.

### Task 2 — Verbatim transcription \+ abstention in the model prompt

- **Audit:** read the current extraction prompt.  
- **Change:** instruct the model to **transcribe each field verbatim from visible text only**, and explicitly: *"If a field is not legible or not visible, return null. Never infer a brand or any field from packaging appearance, color, or shape."* Return **structured JSON** per field with `value` \+ a `legible` / `confidence` flag.  
- **Acceptance:** the Corona shots return "Corona Extra" or null (never "Dos Equis"/"Oro"); the OTR back-of-can returns null for brand (never "Frankie Noir").

### Task 3 — Orientation, skew, and glare handling

- **Change:** auto-detect and correct rotation/skew before inference (handle \~90° rotations like the Miller Lite can — e.g. EXIF orientation \+ a deskew pass). Consider a glare/contrast normalization step.  
- **Change (UX):** allow uploading **front \+ back as two images** — the brand is usually on the front; mandatory fine print (warning, ABV, producer) is often on the back. Merge fields across both before verifying.  
- **Acceptance:** rotated labels are read; a back-only photo with no brand prompts for the front (or is flagged NEEDS REVIEW) instead of hallucinating a brand.

### Task 4 — Per-beverage-type required-field logic

- **Change:** add beverage type (form input or inferred \+ confirmed). Drive the required/conditional/skip decision for every field off the matrix in §3.  
- **Critical:** a missing ABV on **beer** must NOT auto-FAIL. Treat as N/A unless it's a flavored malt beverage.  
- **Acceptance:** Miller Lite and Corona no longer FAIL solely because ABV wasn't found.

### Task 5 — Verify net contents, class/type, and producer (not just extract)

- **Change:** promote these from the "not verified" block into verified checks. Where the application has no expected value to match against, verify **presence \+ well-formedness** (is there a net-contents statement; a class/type; a producer name & address) rather than a value match.  
- **Acceptance:** net contents appears as a checked field with PASS / FAIL / NEEDS REVIEW.

### Task 6 — Wine sulfite declaration \+ import country-of-origin

- **Change (wine, and spirits if applicable):** check for "Contains sulfites" / a sulfiting-agent statement. **Imports (wine \+ beer):** check for a country-of-origin statement.  
- **Acceptance:** the Caymus label shows a sulfite-declaration check; Corona (imported) shows a country-of-origin check.

### Task 7 — Fuzzy / normalized brand matching

- **Change:** replace exact equality with: case-insensitive, punctuation- and whitespace- normalized comparison, plus a fuzzy match (e.g. `rapidfuzz` token-set ratio) with a tunable threshold. Add a **"close — needs human review"** band rather than binary pass/fail.  
- **Acceptance:** "Kirkland Signature" vs "KIRKLAND" and "STONE'S THROW" vs "Stone's Throw" match or land in NEEDS REVIEW — not hard REJECT.

### Task 8 — Strict government-warning check

- **Change:** enforce exact wording **and** punctuation; "GOVERNMENT WARNING" in all caps; the "S" in Surgeon and "G" in General capitalized; a single statement set apart from other text. Bold cannot be reliably detected from OCR text — **document this limitation** and at minimum enforce all-caps \+ exact wording.  
- **Acceptance:** a title-case "Government Warning" or reworded text FAILs; the exact standard text PASSes.

**Suggested order:** 1 → 2 → 7 → 4 → 5 → 8 → 6 → 3\.

---

## 5\. Constraints (from the stakeholder brief — do not regress these)

- **Latency:** results must come back in **\~5 seconds**. A prior vendor's 30–40 s/label killed adoption. Keep any per-label pipeline (incl. tiling) under budget; benchmark it.  
- **Network:** the agency firewall **blocks outbound traffic to many domains**. Prefer local/in-process inference; if any cloud API is used, document it as a dependency that may be blocked, and provide a local fallback if feasible.  
- **Users:** wide range of tech comfort (much of the team is 50+). Keep the UI **clean and obvious — no hidden buttons, no hunting**. Don't add complexity that hurts the non-technical user.  
- **Prototype scope:** no PII storage, no document retention, **no COLA integration**.  
- **Batch:** importers submit 200–300 labels at once; batch upload is a desired feature. Keep the per-label logic reusable so batch can call it.

---

## 6\. Regulatory references (for behavior, not for the agent to re-derive)

- Wine: **27 CFR Part 4** — ABV `4.36`, sulfites `4.32(e)`.  
- Distilled spirits: **27 CFR Part 5** — ABV `5.65`, same-field-of-vision (brand/ABV/class) `5.61`.  
- Beer / malt beverages: **27 CFR Part 7** — ABV (conditional) `7.63(a)(3)`, ABV format `7.65`, net contents `7.70`, name/address `7.66–7.68`, country of origin `7.69`.  
- Government health warning: **27 CFR Part 16** — required ≥0.5% ABV (`16.20`); exact wording, caps, single statement.  
- **Heads-up, NOT current law:** TTB published proposed rules (Jan 2025\) to make an ABV statement mandatory on **all** beer and add an "Alcohol Facts" panel, with a multi-year compliance window. Do **not** build to these yet; keep beer-ABV conditional.

---

## 7\. Regression fixtures (build these as test cases)

| \# | Label (type) | Photo issue | Expected brand / ABV | Current (broken) | Target behavior |
| :---- | :---- | :---- | :---- | :---- | :---- |
| 1 | Miller Lite (beer) | rotated \~90° | Miller Lite / 4.2 | brand "Lite", ABV —, warning — all FAIL | With deskew+full-res: read full brand; **ABV not required → no FAIL**; warning read if legible |
| 2 | Kirkland Tequila Blanco (spirits) | clean, straight-on | Kirkland(/Signature) / 40 | "Kirkland Signature" vs "KIRKLAND" → REJECT | Normalized/fuzzy match → APPROVE (or NEEDS REVIEW); ABV 40=40% pass; warning exact pass |
| 3 | Corona Extra (beer, imported) | glare \+ angle | Corona Extra / 4.6 | brand "Dos Equis"/"Oro"; ABV —; warning — | Read "Corona Extra" or null (never wrong brand); ABV read from fine print (or N/A for beer); add country-of-origin check (Mexico) |
| 4 | OTR / On the Rocks (spirits RTD) | **back of can only** | OTR / 20 | brand "Frankie Noir" (hallucinated) | Brand on front not in frame → return null, prompt for front / NEEDS REVIEW; never hallucinate |
| 5 | Caymus-Suisun (wine) | busy back label, tiny ABV | Caymus / 14.2 | brand pass, ABV — FAIL (honest), warning pass | Preserve good abstention; with full-res read ABV 14.2; add sulfite check ("Contains sulfites" present → pass) |

Fixture 5 is the **good-behavior baseline** (honest abstention) — preserve it while fixing the rest.

---

## 8\. Out of scope / known limitations to document

- No COLA system integration; standalone prototype only.  
- Bold-text detection from OCR is unreliable — document and enforce caps \+ exact text instead.  
- State-law ABV requirements for beer are not modeled (federal COLA review only).

