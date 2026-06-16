"""Gradio UI for the TTB label verifier.

One screen, no login. The interface stays deliberately plain; the design
budget goes to plain-English wording and a big, unmissable verdict, per the
build guide's UX philosophy. The same orchestrator.verify_label() that the
tests exercise is what this screen calls.
"""

import html

import gradio as gr

from orchestrator import verify_label, DISPLAY_ONLY

SAMPLE_BRAND = "Old Tom Distillery"
SAMPLE_ABV = "45"

# verdict -> (background color, display label)
VERDICT_STYLE = {
    "APPROVE": ("#1a7f37", "\u2713 APPROVE"),
    "NEEDS REVIEW": ("#9a6700", "\u26a0 NEEDS REVIEW"),
    "REJECT": ("#cf222e", "\u2717 REJECT"),
}

INITIAL_HTML = (
    '<div style="padding:24px;border:1px dashed #b0b0b0;border-radius:10px;'
    'text-align:center;color:#555;font-size:16px;">'
    'Enter the expected brand name and alcohol content, upload a label photo, '
    'then press <b>Verify</b>.</div>'
)


def load_sample():
    """Pre-fill the expected values with the Old Tom Distillery example."""
    return SAMPLE_BRAND, SAMPLE_ABV


def _banner(verdict: str, message: str) -> str:
    color, label = VERDICT_STYLE.get(verdict, ("#57606a", verdict))
    return (
        f'<div style="background:{color};color:#fff;padding:22px;'
        f'border-radius:10px;text-align:center;margin-bottom:16px;">'
        f'<div style="font-size:32px;font-weight:800;">{label}</div>'
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
            '<table style="width:100%;border-collapse:collapse;font-size:15px;">'
            '<thead><tr style="background:#f3f3f3;text-align:left;">'
            '<th style="padding:8px;">Field</th>'
            '<th style="padding:8px;">Expected</th>'
            '<th style="padding:8px;">Read from label</th>'
            '<th style="padding:8px;">Result</th>'
            '<th style="padding:8px;">Why</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    # Other fields read off the label, shown for reference only.
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
            '<div style="margin-top:14px;color:#555;font-size:14px;">'
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


with gr.Blocks(title="TTB Label Verifier") as demo:
    gr.Markdown(
        "# TTB Label Verifier\n"
        "Check an alcohol-beverage label photo against the application's "
        "expected values."
    )
    with gr.Row():
        with gr.Column(scale=1):
            brand_in = gr.Textbox(label="Expected brand name (from application)")
            abv_in = gr.Textbox(label="Expected alcohol content (from application)")
            sample_btn = gr.Button("Load sample")
            image_in = gr.Image(label="Label photo", type="filepath", sources=["upload"])
            verify_btn = gr.Button("Verify", variant="primary", size="lg")
        with gr.Column(scale=1):
            output = gr.HTML(value=INITIAL_HTML)

    sample_btn.click(load_sample, outputs=[brand_in, abv_in])
    verify_btn.click(on_verify, inputs=[brand_in, abv_in, image_in], outputs=[output])


if __name__ == "__main__":
    demo.launch()
