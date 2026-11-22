"""Our own OCR engine (plan 2026-11-21 v2 §9): RapidOCR, ONNX models shipped in the wheel, CPU only, nothing sent off the
server. It fills the `OcrEngine` port of the PDF reader (`source_model.OcrEngine`): the words of one page, each with its
box in the page's own coordinates (points, top-left origin, as pdfplumber gives them), so an OCR word is anchored and
located exactly like a word of the text layer.

The page is rendered with pdfium at `SCALE` (2.5 × 72 dpi = 180 dpi, enough for 8 pt table text); RapidOCR returns text
lines with a box per character (`return_word_box`), which are cut at spaces into words. Where the characters' boxes do
not line up with the text (a recogniser quirk), a line's words share its box in proportion to their lengths.

    engine = RapidOcr()                      # loads the models on first use (about 1 s)
    parse_document(data, name, ocr=engine)   # scanned pages read, their words located like any other
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from importlib import metadata
from io import BytesIO
from typing import Any

from modeler_intake.source.regions import round_box
from modeler_intake.source_model import Word

SCALE = 2.5            # render scale (1.0 = 72 dpi): a reading parameter, part of the engine's version
MIN_CONFIDENCE = 0.5   # a recognised line below this is dropped (stamps, smudges, hatching)


@lru_cache(maxsize=1)
def _recogniser() -> Any:
    from rapidocr_onnxruntime import RapidOCR  # imported here: the models load only when a scan is read

    return RapidOCR()


def _version() -> str:
    try:
        return metadata.version("rapidocr-onnxruntime")
    except metadata.PackageNotFoundError:
        return "missing"


def _line_words(text: str, line_box: Sequence[Sequence[float]], char_boxes: Sequence[Any] | None,
                scale: float) -> list[tuple[str, tuple[float, float, float, float]]]:
    """A recognised line cut into words at spaces, each word with its box in points."""
    def to_box(points: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return (min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale)

    tokens: list[tuple[str, int, int]] = []          # word, first and last index of its characters in `text`
    start = None
    for i, ch in enumerate(text + " "):
        if ch.isspace():
            if start is not None:
                tokens.append((text[start:i], start, i - 1))
                start = None
        elif start is None:
            start = i
    if not tokens:
        return []
    boxes = list(char_boxes or [])
    if len(boxes) == len(text):
        index = {i: i for i in range(len(text))}
    elif len(boxes) == len(text.replace(" ", "")):       # the boxes skip the spaces
        index, k = {}, 0
        for i, ch in enumerate(text):
            if not ch.isspace():
                index[i] = k
                k += 1
    else:
        index = None
    out = []
    if index is not None:
        for word, first, last in tokens:
            points = [p for i in range(first, last + 1) if i in index for p in boxes[index[i]]]
            out.append((word, to_box(points)))
        return out
    x0, top, x1, bottom = to_box(line_box)               # proportional fallback
    total = sum(len(w) for w, _, _ in tokens) + max(len(tokens) - 1, 0)
    cursor = x0
    for word, _, _ in tokens:
        width = (x1 - x0) * len(word) / total
        out.append((word, (cursor, top, cursor + width, bottom)))
        cursor += width + (x1 - x0) / total
    return out


def words_of_image(image: Any, *, scale: float = 1.0) -> list[Word]:
    """The words of an image (a PIL image or an array), boxes in pixels divided by `scale`, in reading order."""
    result, _ = _recogniser()(image, return_word_box=True)
    found: list[tuple[str, tuple[float, float, float, float]]] = []
    for line in result or []:
        line_box, text, confidence = line[0], unicodedata.normalize("NFKC", str(line[1])), float(line[2])
        if confidence < MIN_CONFIDENCE or not text.strip():
            continue
        char_boxes = line[3] if len(line) > 3 else None
        found.extend(_line_words(text, line_box, char_boxes, scale))
    found.sort(key=lambda w: (round(w[1][1] / 4), w[1][0]))   # top to bottom (4-point bands), then left to right
    return [Word(index=k, text=text, box=round_box(box)) for k, (text, box) in enumerate(found, start=1)]


class RapidOcr:
    """The PDF reader's OCR engine: `words(data, page)` reads one page (1-based) of a PDF's bytes."""

    name = "rapidocr"

    def __init__(self, scale: float = SCALE) -> None:
        self.scale = scale
        self.version = f"{_version()}@{scale:g}"

    def words(self, data: bytes, page: int) -> Sequence[Word]:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(data)
        try:
            image = document[page - 1].render(scale=self.scale).to_pil()
        finally:
            document.close()
        return words_of_image(image, scale=self.scale)


def image_to_pdf(data: bytes) -> bytes:
    """An image (PNG, JPEG, TIFF…) as a one-page PDF at 72 dpi per pixel / 2.5, so the PDF reader and its OCR read it
    like a scanned page (an image file has no text layer of its own)."""
    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        frames = []
        for i in range(getattr(image, "n_frames", 1)):
            image.seek(i)
            frames.append(image.convert("RGB"))
    out = BytesIO()
    frames[0].save(out, format="PDF", save_all=True, append_images=frames[1:], resolution=72 * SCALE)
    return out.getvalue()
