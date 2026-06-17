"""Vision-based field extraction for TTB label images.

Sends a (downscaled) label image to a fast vision-capable Claude model and
asks for the label's fields as structured JSON. Downscaling before upload is
the main lever for staying under the ~5-second response bar (Sarah's failed-
vendor story): a smaller image means less to encode, upload, and process,
and labels stay legible well below full camera resolution.
"""

import base64
import io
import json
import re

from anthropic import Anthropic
from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()  # pulls ANTHROPIC_API_KEY from .env when running locally

# Fast, low-cost, vision-capable model. Reading six fields is a simple task,
# so the cheapest fast tier is the right fit and best defends the latency
# budget. Swap this string to change models; nothing else needs to change.
MODEL = "claude-haiku-4-5-20251001"

# Longest edge (px) an uploaded label is resized to before sending. Anthropic's
# vision models operate best around 1568px on the long edge, so we size close
# to that: large enough to keep small print (the government warning) legible,
# while still cutting upload/processing time versus a full-resolution photo.
MAX_IMAGE_EDGE = 1536

# Fields the model is asked to read - all now verified downstream (see
# orchestrator.assemble_verdict). sulfite_declaration is only checked for wine.
FIELDS = [
    "brand_name",
    "class_type",
    "abv",
    "net_contents",
    "producer",
    "government_warning",
    "sulfite_declaration",
    "country_of_origin",
]

_PROMPT = (
    "You are reading a U.S. alcohol-beverage label. You may be given one or two "
    "photos of the SAME product (for example its front and back); read each field "
    "from whichever photo shows it, and if it appears on more than one, use the "
    "clearest. Extract these fields and respond with ONLY a JSON object - no "
    "prose, no markdown fences. Use exactly these keys: " + ", ".join(FIELDS) + ".\n"
    "\n"
    "Transcription rules:\n"
    "- Transcribe every field VERBATIM from the printed text you can actually "
    "see. Copy it exactly: preserve capitalization, punctuation, and digits. Do "
    "NOT normalize, round, reformat, translate, or paraphrase. If the label reads "
    '"4.6% ALC/VOL", then abv is "4.6%" - never "5%".\n'
    "- Never infer a value from packaging appearance, logo style, color, or "
    "bottle shape. brand_name in particular must come only from legible printed "
    "text, never from recognizing the product.\n"
    "- class_type: the beverage's class or type designation exactly as printed - "
    'for example "Lager", "Imported Beer", "Kentucky Straight Bourbon Whiskey", '
    'or "Red Wine".\n'
    "- producer: capture the COMPLETE name-and-address statement. Include BOTH "
    "the manufacturer/bottler line AND any separate importer line - for example "
    '"CERVECERIA MODELO, NAVA, MEXICO" together with "IMPORTED BY CROWN IMPORTS, '
    'CHICAGO, IL". Join multiple lines with "; ".\n'
    "- government_warning: this required statement is often small, low-contrast "
    "print near the bottom or side. Read it carefully and transcribe exactly what "
    "is legibly printed; do not reconstruct it from memory.\n"
    "- sulfite_declaration: the sulfiting-agent declaration if present (for "
    'example "CONTAINS SULFITES"); use null if the label has no such statement.\n'
    "- country_of_origin: the country-of-origin statement if present (for "
    'example "Product of Mexico", "Imported from France", "Produced in Italy"); '
    "use null if the label states no country of origin.\n"
    "- If a field is illegible or not present on the label, set its value to "
    "null. null is the correct, honest answer when you cannot read the text - "
    "never guess a plausible value to fill a field."
)


# A single client, created on first use and reused across calls. Reusing it
# (rather than constructing a new Anthropic() per request) avoids repeated
# setup cost and connection warmup on every verification. Lazy init keeps the
# module importable without a key, which the unit tests rely on.
_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    return _client


def _downscale_to_jpeg(image_bytes: bytes, max_edge: int = MAX_IMAGE_EDGE) -> bytes:
    """Apply camera orientation, then resize so the longest edge is <= max_edge;
    return JPEG bytes.

    Orientation matters before anything else: phones store a landscape sensor
    frame plus an EXIF orientation flag, so a portrait photo whose flag we ignore
    reaches the model rotated 90 degrees. That is what made the Corona back label
    read as a sideways "Czechvar". exif_transpose rewrites the pixels upright and
    drops the now-applied flag; it is idempotent and a no-op when there is no flag
    (e.g. the synthetic fixtures, or an upload Gradio already transposed).

    (Automatic deskew of residual small tilt was evaluated and deliberately left
    out: without a robust text-line detector the projection-profile heuristic
    locks onto glare bands and rotates straight labels crooked - the opposite of
    helpful on the glare photos this tool targets. See the build notes.)
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge))  # preserves aspect ratio, only shrinks
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _strip_to_json(text: str) -> str:
    """Best-effort cleanup if the model wraps JSON in markdown fences."""
    text = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.DOTALL)
    return fence.group(1).strip() if fence else text


def extract_fields(image_bytes) -> dict:
    """Image bytes (or a list of images, e.g. the front + back of one product)
    in -> dict of label fields. Multiple images are sent in a SINGLE request and
    the model reads each field from whichever image shows it. Raises on API or
    parse failure.
    """
    images = image_bytes if isinstance(image_bytes, (list, tuple)) else [image_bytes]

    content = []
    for img in images:
        jpeg = _downscale_to_jpeg(img)
        b64 = base64.standard_b64encode(jpeg).decode("ascii")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })
    content.append({"type": "text", "text": _PROMPT})

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )

    raw = _strip_to_json(message.content[0].text)
    data = json.loads(raw)
    # Guarantee every expected key exists, and normalize the model's "abstain"
    # signal - JSON null, or an omitted key - to an empty string, which the
    # comparison layer already treats as "not read". (Without this, str(None)
    # would leak the literal "None" into a field and be mistaken for a value.)
    out = {}
    for field in FIELDS:
        value = data.get(field)
        out[field] = "" if value is None else str(value)
    return out


if __name__ == "__main__":
    # Manual smoke test: python extractor.py path/to/label.png
    import sys
    import time

    if len(sys.argv) != 2:
        print("Usage: python extractor.py <image_path>")
        sys.exit(1)

    with open(sys.argv[1], "rb") as f:
        image_data = f.read()

    start = time.time()
    result = extract_fields(image_data)
    elapsed = time.time() - start

    print(json.dumps(result, indent=2))
    print(f"\nExtraction took {elapsed:.2f}s")
