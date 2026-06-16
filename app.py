"""Gradio UI for the TTB label verifier.

One screen, no login. The interface stays deliberately plain; the design
budget goes to plain-English wording and a big, unmissable verdict, per the
build guide's UX philosophy. A second tab adds batch verification for the
peak-season importer case (Janet's request) and reuses the same orchestrator.
"""

import csv
import html
import os
import tempfile

import gradio as gr

from orchestrator import verify_label, verify_batch, summarize, DISPLAY_ONLY

SAMPLE_BRAND = "Old Tom Distillery"
SAMPLE_ABV = "45"

# verdict -> (background color, display label)
VERDICT_STYLE = {
    "APPROVE": ("#1a7f37", "APPROVE"),
    "NEEDS REVIEW": ("#9a6700", "NEEDS REVIEW"),
    "REJECT": ("#cf222e", "REJECT"),
}

# A consistent system font stack for injected HTML, so the verdict and tables
# render in the same face as the rest of the interface.
FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, "
        "Arial, sans-serif")

INITIAL_HTML = (
    f'<div style="font-family:{FONT};padding:24px;border:1px dashed #b0b0b0;'
    'border-radius:10px;text-align:center;color:#555;font-size:16px;">'
    'Enter the expected brand name and alcohol content, upload a label photo, '
    'then press <b>Verify</b>.</div>'
)

BATCH_INITIAL_HTML = (
    f'<div style="font-family:{FONT};padding:24px;border:1px dashed #b0b0b0;'
    'border-radius:10px;text-align:center;color:#555;font-size:16px;">'
    'Upload several label photos and a CSV of expected values '
    '(columns: filename, brand, abv), then press <b>Run batch</b>.</div>'
)


# --------------------------------------------------------------------------
# Single-label rendering
# --------------------------------------------------------------------------

def load_sample():
    """Pre-fill the expected values with the Old Tom Distillery example."""
    return SAMPLE_BRAND, SAMPLE_ABV


def _banner(verdict: str, message: str) -> str:
    color, label = VERDICT_STYLE.get(verdict, ("#57606a", verdict))
    return (
        f'<div style="font-family:{FONT};background:{color};color:#fff;'
        f'padding:22px;border-radius:10px;text-align:center;margin-bottom:16px;">'
        f'<div style="font-size:34px;font-weight:800;letter-spacing:0.3px;">{label}</div>'
        f'<div style="font-size:16px;margin-top:8px;">{html.escape(message)}</div>'
        f'</div>'
    )


def _check_row(field, expected, found, passed, reason) -> str:
    color = "#1a7f37" if passed else "#cf222e"
    badge = "PASS" if passed else "FAIL"
    return (
        '<tr style="border-bottom:1px solid #eee;">'
        f'<td style="padding:8px;font-weight:600;">{html.escape(field)}</td>'
        f'<td style="padding:8px;">{html.escape(expected) or "&mdash;"}</td>'
        f'<td style="padding:8px;">{html.escape(found) or "&mdash;"}</td>'
        f'<td style="padding:8px;color:{color};font-weight:700;">{badge}</td>'
        f'<td style="padding:8px;color:#444;">{html.escape(reason)}</td>'
        '</tr>'
    )


def _results_html(result) -> str:
    parts = [_banner(result.verdict, result.message)]

    if result.checks:
        rows = "".join(
            _check_row(c.field, c.expected, c.found, c.passed, c.reason)
            for c in result.checks
        )
        parts.append(
            '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">'
            f'<table style="font-family:{FONT};width:100%;min-width:560px;'
            'border-collapse:collapse;font-size:15px;">'
            '<thead><tr style="background:#f3f3f3;text-align:left;">'
            '<th style="padding:8px;">Field</th>'
            '<th style="padding:8px;">Expected</th>'
            '<th style="padding:8px;">Read from label</th>'
            '<th style="padding:8px;">Result</th>'
            '<th style="padding:8px;">Why</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>'
        )

    extra = [
        (f.replace("_", " ").title(), result.extracted.get(f, ""))
        for f in DISPLAY_ONLY
        if (result.extracted.get(f) or "").strip()
    ]
    if extra:
        items = "".join(
            f'<li style="margin:2px 0;"><b>{html.escape(name)}:</b> '
            f'{html.escape(val)}</li>'
            for name, val in extra
        )
        parts.append(
            f'<div style="font-family:{FONT};margin-top:14px;color:#555;'
            'font-size:14px;">'
            '<div style="font-weight:600;margin-bottom:4px;">'
            'Other details read from the label (not verified):</div>'
            f'<ul style="margin:0;padding-left:20px;">{items}</ul></div>'
        )

    return "".join(parts)


def on_verify(expected_brand, expected_abv, image_path):
    if not image_path:
        return _banner("NEEDS REVIEW", "Please upload a label image first.")
    if not (expected_brand or "").strip() or not (expected_abv or "").strip():
        return _banner(
            "NEEDS REVIEW",
            "Please enter the expected brand name and alcohol content first.",
        )

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    result = verify_label(expected_brand, expected_abv, image_bytes)
    return _results_html(result)


# --------------------------------------------------------------------------
# Batch rendering
# --------------------------------------------------------------------------

def _parse_expected_csv(csv_path: str) -> dict:
    """Build {filename: (brand, abv)} from the expected-values CSV."""
    mapping = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("filename") or "").strip()
            if name:
                mapping[name] = (
                    (row.get("brand") or "").strip(),
                    (row.get("abv") or "").strip(),
                )
    return mapping


def _verdict_badge(verdict: str) -> str:
    color, label = VERDICT_STYLE.get(verdict, ("#57606a", verdict))
    return (
        f'<span style="background:{color};color:#fff;padding:3px 10px;'
        f'border-radius:6px;font-weight:700;font-size:13px;">{label}</span>'
    )


def _batch_html(results, summary, unmatched) -> str:
    s = summary
    parts = [
        f'<div style="font-family:{FONT};background:#f3f3f3;padding:16px;'
        'border-radius:10px;margin-bottom:14px;font-size:16px;">'
        f'<b>{s["total"]} label(s) checked.</b> &nbsp; '
        f'<span style="color:#1a7f37;font-weight:700;">{s["APPROVE"]} approve</span> &middot; '
        f'<span style="color:#cf222e;font-weight:700;">{s["REJECT"]} reject</span> &middot; '
        f'<span style="color:#9a6700;font-weight:700;">{s["NEEDS REVIEW"]} needs review</span>'
        '</div>'
    ]

    def cell(checks, field):
        c = checks.get(field)
        if c is None:
            return '<td style="padding:8px;color:#999;">&mdash;</td>'
        color = "#1a7f37" if c.passed else "#cf222e"
        return (f'<td style="padding:8px;color:{color};font-weight:700;">'
                f'{"PASS" if c.passed else "FAIL"}</td>')

    rows = []
    for item in results:
        r = item["result"]
        checks = {c.field: c for c in r.checks}
        rows.append(
            '<tr style="border-bottom:1px solid #eee;">'
            f'<td style="padding:8px;">{html.escape(item["filename"])}</td>'
            f'<td style="padding:8px;">{_verdict_badge(r.verdict)}</td>'
            f'{cell(checks, "Brand name")}'
            f'{cell(checks, "Alcohol content")}'
            f'{cell(checks, "Government warning")}'
            '</tr>'
        )
    parts.append(
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">'
        f'<table style="font-family:{FONT};width:100%;min-width:560px;'
        'border-collapse:collapse;font-size:15px;">'
        '<thead><tr style="background:#f3f3f3;text-align:left;">'
        '<th style="padding:8px;">File</th>'
        '<th style="padding:8px;">Verdict</th>'
        '<th style="padding:8px;">Brand</th>'
        '<th style="padding:8px;">ABV</th>'
        '<th style="padding:8px;">Warning</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )

    if unmatched:
        names = ", ".join(html.escape(n) for n in unmatched)
        parts.append(
            f'<div style="font-family:{FONT};margin-top:12px;color:#9a6700;'
            f'font-size:14px;">Skipped (no matching row in the CSV): {names}</div>'
        )

    return "".join(parts)


def _make_template_csv() -> str:
    """Write an example-filled CSV template to a temp file so users can
    download it and just fill in their own rows (no format guesswork)."""
    path = os.path.join(tempfile.gettempdir(), "ttb_expected_values_template.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "brand", "abv"])
        writer.writerow(["your_label_filename.png", "Your Brand Name", "45"])
    return path


TEMPLATE_CSV = _make_template_csv()


def on_batch(image_paths, csv_path):
    if not image_paths or not csv_path:
        return _banner(
            "NEEDS REVIEW",
            "Upload both the label images and the expected-values CSV.",
        )

    mapping = _parse_expected_csv(csv_path)
    items, unmatched = [], []
    for path in image_paths:
        name = os.path.basename(path)
        if name in mapping:
            brand, abv = mapping[name]
            with open(path, "rb") as fh:
                items.append({
                    "filename": name, "brand": brand, "abv": abv,
                    "image_bytes": fh.read(),
                })
        else:
            unmatched.append(name)

    if not items:
        return _banner(
            "NEEDS REVIEW",
            "None of the uploaded images matched a filename in the CSV.",
        )

    results = verify_batch(items)
    return _batch_html(results, summarize(results), unmatched)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

with gr.Blocks(title="TTB Label Verifier") as demo:
    gr.HTML(
        f'<div style="font-family:{FONT};">'
        '<div style="font-size:30px;font-weight:800;margin-bottom:2px;">'
        'TTB Label Verifier</div>'
        '<div style="font-size:15px;color:#555;">Check an alcohol-beverage '
        "label photo against the application's expected values.</div>"
        '</div>'
    )

    with gr.Tabs():
        with gr.Tab("Single label"):
            with gr.Row():
                with gr.Column(scale=1):
                    brand_in = gr.Textbox(
                        label="Expected brand name (from application)",
                        info="Type it as printed on the label, e.g. Old Tom Distillery.",
                    )
                    abv_in = gr.Textbox(
                        label="Expected alcohol content (from application)",
                        info="Percent alcohol by volume - e.g. 4.6 for a beer, 45 for spirits. Enter the percentage, not the proof.",
                    )
                    sample_btn = gr.Button("Load sample")
                    image_in = gr.Image(label="Label photo", type="filepath", sources=["upload"])
                    verify_btn = gr.Button("Verify", variant="primary", size="lg")
                with gr.Column(scale=1):
                    output = gr.HTML(value=INITIAL_HTML)

            sample_btn.click(load_sample, outputs=[brand_in, abv_in])
            verify_btn.click(on_verify, inputs=[brand_in, abv_in, image_in], outputs=[output])

        with gr.Tab("Batch"):
            gr.Markdown(
                "Upload many label photos plus a CSV of expected values "
                "(columns: `filename`, `brand`, `abv`). Each image is matched "
                "to its row by filename. New here? Download the template below "
                "and fill in your rows."
            )
            with gr.Row():
                with gr.Column(scale=1):
                    gr.DownloadButton(
                        "Download CSV template", value=TEMPLATE_CSV, size="sm"
                    )
                    batch_images = gr.File(
                        label="Label photos",
                        file_count="multiple",
                        file_types=["image"],
                        type="filepath",
                    )
                    batch_csv = gr.File(
                        label="Expected values (CSV)",
                        file_types=[".csv"],
                        type="filepath",
                    )
                    batch_btn = gr.Button("Run batch", variant="primary", size="lg")
                with gr.Column(scale=1):
                    batch_output = gr.HTML(value=BATCH_INITIAL_HTML)

            batch_btn.click(on_batch, inputs=[batch_images, batch_csv], outputs=[batch_output])


if __name__ == "__main__":
    demo.launch()
