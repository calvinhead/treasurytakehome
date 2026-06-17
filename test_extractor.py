"""Plumbing test for multi-image extraction: two images must go in ONE request
as two image blocks. A fake client stands in for Haiku so no network call is
made (the existing live coverage is in test_real_photo_regression.py)."""
import io
import json

from PIL import Image

import extractor


def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), (200, 180, 120)).save(buf, format="PNG")
    return buf.getvalue()


def test_two_images_go_in_one_request(monkeypatch):
    captured = {}

    class _Text:
        text = json.dumps({f: None for f in extractor.FIELDS})

    class _Msg:
        content = [_Text()]

    class _Messages:
        def create(self, **kwargs):
            captured["content"] = kwargs["messages"][0]["content"]
            return _Msg()

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(extractor, "_client", _Client())

    img = _tiny_png()
    fields = extractor.extract_fields([img, img])

    content = captured["content"]
    assert sum(b["type"] == "image" for b in content) == 2   # both images, one request
    assert sum(b["type"] == "text" for b in content) == 1    # one shared prompt
    # null -> "" normalization keeps every key present.
    assert set(fields) == set(extractor.FIELDS)
    assert all(v == "" for v in fields.values())


def test_single_image_bytes_still_one_block(monkeypatch):
    captured = {}

    class _Text:
        text = json.dumps({f: None for f in extractor.FIELDS})

    class _Msg:
        content = [_Text()]

    class _Messages:
        def create(self, **kwargs):
            captured["content"] = kwargs["messages"][0]["content"]
            return _Msg()

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(extractor, "_client", _Client())

    extractor.extract_fields(_tiny_png())   # plain bytes, not a list
    assert sum(b["type"] == "image" for b in captured["content"]) == 1
