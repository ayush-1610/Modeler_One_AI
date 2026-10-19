"""Redesign §3.2 (R3d): the digitizer lists the figures placed in a PDF, where each sits on its page, without decoding
them. The PDFs here are built by the test with pypdf's own objects, so every position is known."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject

from modeler_intake.documents import DocumentError, pdf_figures

pytestmark = pytest.mark.req("T-45")


def _image(writer: PdfWriter, width: int, height: int):
    image = DecodedStreamObject()
    image.set_data(bytes([255]) * width * height)
    image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                  NameObject("/Width"): NumberObject(width), NameObject("/Height"): NumberObject(height),
                  NameObject("/ColorSpace"): NameObject("/DeviceGray"), NameObject("/BitsPerComponent"): NumberObject(8)})
    return writer._add_object(image)


def _page(writer: PdfWriter, content: bytes, xobjects: dict[str, object], *, rotate: int = 0) -> None:
    page = writer.add_blank_page(width=600, height=800)
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject(
        {NameObject(k): v for k, v in xobjects.items()})})
    if rotate:
        page[NameObject("/Rotate")] = NumberObject(rotate)


def _bytes(writer: PdfWriter) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_a_placed_image_is_listed_where_it_sits_on_the_page():
    writer = PdfWriter()
    _page(writer, b"q 300 0 0 200 150 500 cm /Im1 Do Q q 20 0 0 20 10 10 cm /Logo Do Q",
          {"/Im1": _image(writer, 800, 600), "/Logo": _image(writer, 32, 32)})
    [figure] = pdf_figures(_bytes(writer))                 # the 20-pt logo is left out
    assert (figure.page, figure.name, figure.width, figure.height) == (1, "Im1", 800, 600)
    assert figure.box == (0.25, 0.125, 0.75, 0.375)       # x 150–450 of 600; y 500–700 of 800, counted from the top


def test_an_image_inside_a_form_follows_the_forms_matrix_and_a_rotated_page_turns_the_box():
    writer = PdfWriter()
    form = DecodedStreamObject()
    form.set_data(b"q 100 0 0 100 0 0 cm /Im1 Do Q")
    form.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                 NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(100), FloatObject(100)]),
                 NameObject("/Matrix"): ArrayObject([FloatObject(v) for v in (2, 0, 0, 2, 0, 0)]),
                 NameObject("/Resources"): DictionaryObject({NameObject("/XObject"): DictionaryObject(
                     {NameObject("/Im1"): _image(writer, 400, 400)})})})
    form_ref = writer._add_object(form)
    _page(writer, b"q 1 0 0 1 60 80 cm /Fm1 Do Q", {"/Fm1": form_ref})
    _page(writer, b"q 1 0 0 1 60 80 cm /Fm1 Do Q", {"/Fm1": form_ref}, rotate=90)
    upright, turned = pdf_figures(_bytes(writer))
    assert upright.box == (0.1, 0.65, 0.4333, 0.9)        # 200 × 200 pt at (60, 80): x 60–260, y 80–280
    assert turned.page == 2 and turned.box == (0.1, 0.1, 0.35, 0.4333)   # a quarter turn clockwise


def test_a_file_that_is_not_a_pdf_says_so():
    with pytest.raises(DocumentError, match="figures could not be listed"):
        pdf_figures(b"not a pdf")
