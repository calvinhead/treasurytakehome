# CLAUDE.md — TTB Label Verifier

Standing context for this project, loaded every session. Kept short on purpose — the active build plan (one-time task list, acceptance criteria, fixtures) lives in `TTB_VERIFIER_BUILD_SPEC.md`.

## What this is

A Gradio app that checks an alcohol-beverage label photo against an application's expected values and returns APPROVE / REJECT / NEEDS REVIEW. Has single-label and batch modes. Prototype / proof-of-concept, not production.

## Stack & conventions

- Python \+ Gradio. Prefer Python for everything.  
- Keep per-label verification logic in a reusable function so batch mode can call the same path.  
- Do not regress the UI: it must stay clean and obvious for non-technical users (much of the team is 50+). No hidden controls, no hunting for buttons.

## Hard constraints (do not violate)

- **Latency:** a single label must verify in \~5 seconds. A prior vendor at 30–40s killed adoption.  
- **Network:** the agency firewall blocks outbound traffic to many domains. Prefer local / in-process inference. If any external API is used, document it as possibly-blocked and provide a local fallback where feasible.  
- **No sensitive data:** prototype only — no PII storage, no document retention, no COLA integration.

## Cardinal rule (this caused the main bug)

The model must **transcribe label text verbatim and abstain when it can't read** — return `null` for an unreadable or absent field. It must **never infer a brand (or any field) from packaging appearance, color, or shape.** A confident wrong value is worse than an honest NEEDS REVIEW.

## Domain rules (TTB) — always apply, and branch by beverage type

- **ABV is conditional for beer:** required only for flavored malt beverages (alcohol from added flavors / nonbeverage ingredients). Required for wine and spirits. **Never auto-FAIL beer for a missing ABV.**  
- Always mandatory for every type: brand, class/type, net contents, producer name & address, government warning.  
- **Country of origin** is required for imports.  
- **Sulfite declaration** ("Contains sulfites") is required for wine (and spirits) at ≥10 ppm.  
- **Government warning is format-strict:** exact wording \+ punctuation, "GOVERNMENT WARNING" in ALL CAPS, capital S in Surgeon and G in General, a single statement set apart from other text. Presence alone is not enough.  
- **Brand matching is normalized \+ fuzzy, never exact-string:** case- and punctuation-insensitive; near-matches go to a "needs human review" band rather than auto-REJECT.  
- **Not current law — do not build to it:** TTB's Jan 2025 proposed rules would make ABV mandatory on all beer and add an "Alcohol Facts" panel. Still proposed, multi-year compliance window. Keep beer ABV conditional.

## Active work

See `TTB_VERIFIER_BUILD_SPEC.md` for the prioritized tasks, acceptance criteria, and regression fixtures. Work task-by-task; audit the relevant code and confirm assumptions before editing.  
