"""PowerPoint (`.pptx`, plan 2026-11-26 §7 phase 2): a deck read once with python-pptx into a body, as a Word file is.

Clients put data on slides: dissolution tables and charts, BE ratios with their CIs (three files of the owner's corpus
did). The deck is read slide by slide, in order:

- a paragraph "Slide <n>" opens each slide, then its title and every text frame's paragraphs (a shape inside a group
  too), each line as written;
- a table becomes a body table (a grid of cells, as a Word table);
- a chart becomes a body table of its data, as the chart stores it: a header row of the categories (the x values, e.g.
  the sampling times) and one row per series (its name, then its values), so a dissolution chart is read as numbers,
  not as a picture;
- a picture is a figure (its pixels are not read here: a slide image of a table is named in the warnings);
- the notes under a slide are read as paragraphs after it, marked "Notes:".

The body is then located exactly as a Word body (`docx.locate_docx`: tables with their captions and context lines,
prose runs, figures). Nothing is dropped in silence: a picture's text is not read, so a deck with pictures is
`partly_read`, its reason naming the slides.
"""

from __future__ import annotations

import io
from typing import Any

from modeler_intake.source_model import BodyItem, Figure, PageTable, Paragraph, TableCell

MAX_NAMED = 5


def _number_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    return str(value)


class _Body:
    def __init__(self) -> None:
        self.items: list[BodyItem] = []
        self.figures: list[Figure] = []
        self.paragraphs = 0
        self.tables = 0

    def paragraph(self, text: str, style: str = "") -> None:
        for line in text.splitlines() or [text]:
            if line.strip():
                self.paragraphs += 1
                self.items.append(BodyItem(kind="paragraph", paragraph=Paragraph(index=self.paragraphs, text=line, style=style)))

    def table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        self.tables += 1
        cells = tuple(TableCell(row=r, column=c, text=text)
                      for r, row in enumerate(rows, start=1) for c, text in enumerate(row, start=1))
        self.items.append(BodyItem(kind="table", table=PageTable(index=self.tables, box=None, n_rows=len(rows),
                                                                  n_cols=max(len(r) for r in rows), cells=cells,
                                                                  engine="python-pptx")))

    def figure(self, name: str, slide: int) -> None:
        self.figures.append(Figure(index=len(self.figures) + 1, page=slide, name=name))


def _chart_rows(chart: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for plot in chart.plots:
        categories = [_number_text(c) for c in plot.categories]
        if not rows:
            rows.append([""] + categories)
        for series in plot.series:
            rows.append([str(series.name or "")] + [_number_text(v) for v in series.values])
    return rows


def _shapes(shapes: Any, body: _Body, slide: int, pictures: list[int]) -> None:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            _shapes(shape.shapes, body, slide, pictures)
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            body.table([[cell.text for cell in row.cells] for row in shape.table.rows])
        elif getattr(shape, "has_chart", False) and shape.has_chart:
            title = shape.chart.chart_title.text_frame.text if shape.chart.has_title else ""
            if title.strip():
                body.paragraph(title)
            body.table(_chart_rows(shape.chart))
        elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            body.figure(shape.name or f"picture on slide {slide}", slide)
            pictures.append(slide)
        elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            body.paragraph(shape.text_frame.text)


def read_pptx(data: bytes) -> tuple[tuple[BodyItem, ...], tuple[Figure, ...], tuple[str, ...], tuple[str, ...]]:
    """(body, figures, warnings, unread) of a deck; `unread` names each place whose text is not read (a picture).
    Raises the library's exception for a file it cannot open (the caller makes it `unreadable`)."""
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    body = _Body()
    pictures: list[int] = []
    for n, slide in enumerate(deck.slides, start=1):
        body.paragraph(f"Slide {n}", style="Heading 1")
        _shapes(slide.shapes, body, n, pictures)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text
            if notes.strip():
                body.paragraph(f"Notes: {notes}")
    slides = sorted(set(pictures))
    unread = tuple(f"the picture(s) on slide {s}" for s in slides)
    warnings = tuple(f"PPTX_PICTURE_NOT_READ: slide {s} holds a picture whose text is not read (send its data as a "
                     "table if it holds values)" for s in slides)
    return tuple(body.items), tuple(body.figures), warnings, unread


def unread_reason(unread: tuple[str, ...]) -> str:
    named = "; ".join(unread[:MAX_NAMED]) + (f"; and {len(unread) - MAX_NAMED} more" if len(unread) > MAX_NAMED else "")
    return f"text not read: {named}"
