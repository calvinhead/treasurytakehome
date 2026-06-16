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
from PIL import Image

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

# Fields the model is asked to read. The first three are verified downstream;
# the rest are displayed for the agent's reference.
FIELDS = [
    "brand_name",
    "class_type",
    "abv",
    "net_contents",
    "producer",
    "government_warning",
]

_PROMPT = (
    "You are reading a U.S. alcohol-beverage label. Extract these fields and "
    "respond with ONLY a JSON object - no prose, no markdown fences. "
    "Use exactly these keys: " + ", ".join(FIELDS) + ". "
    "Copy text verbatim as printed and preserve capitalization exactly; this "
    "matters for the government warning. The government warning is often in "
    "small, low-contrast print near the bottom or side of the label - look "
    "carefully and transcribe it in full if any part of it is visible. If a "
    "field is genuinely not visible, set its value to an empty string. For "
    "government_warning, return the full warning text exactly as printed, or "
    "an empty string only if no warning text is present at all."
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
    """Resize so the longest edge is <= max_edge; return JPEG bytes."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((max_edge, max_edge))  # preserves aspect ratio, only shrinks
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _strip_to_json(text: str) -> str:
    """Best-effort cleanup if the model wraps JSON in markdown fences."""
    text = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.DOTALL)
    return fence.group(1).strip() if fence else text


def extract_fields(image_bytes: bytes) -> dict:
    """Image bytes in -> dict of label fields. Raises on API or parse failure."""
    jpeg = _downscale_to_jpeg(image_bytes)
    b64 = base64.standard_b64encode(jpeg).decode("ascii")

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )

    raw = _strip_to_json(message.content[0].text)
    data = json.loads(raw)
    # Guarantee every expected key exists even if the model omitted one.
    return {field: str(data.get(field, "")) for field in FIELDS}


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
