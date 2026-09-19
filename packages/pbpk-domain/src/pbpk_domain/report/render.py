"""Convert a rendered MAR (Markdown) to DOCX and PDF/A-2b via Pandoc (task T-24).

The Markdown produced by :func:`pbpk_domain.report.mar.render_markdown` is the source of truth; Pandoc turns
it into the submission formats. PDF/A-2b is an archival ISO profile the FDA accepts for submissions; we ask
the LaTeX engine for it via the ``pdfx`` package and, when available, verify/repair conformance with
Ghostscript. Pandoc and a LaTeX engine are heavy dependencies, so callers check :func:`pandoc_available`
first; the Markdown path never depends on them.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pbpk_domain.report.mar import MarDocument, render_markdown


class RenderError(Exception):
    pass


def pandoc_available(pandoc: str = "pandoc") -> bool:
    return shutil.which(pandoc) is not None


def render_docx(markdown: str, out_path: Path, *, pandoc: str = "pandoc", reference_doc: Path | None = None) -> Path:
    """Write the MAR as a DOCX. ``reference_doc`` supplies house styles (headers, fonts) if provided."""
    args = [pandoc, "-f", "markdown", "-t", "docx", "-o", str(out_path)]
    if reference_doc is not None:
        args += ["--reference-doc", str(reference_doc)]
    _run_pandoc(args, markdown)
    return out_path


def render_pdf_a(markdown: str, out_path: Path, *, pandoc: str = "pandoc", gs: str = "gs") -> Path:
    """Write the MAR as PDF/A-2b. Pandoc emits a PDF with a PDF/A intent via ``pdfx``; if Ghostscript is
    present the output is normalised to PDF/A-2b, which is the reliable path to a conformant file."""
    header = _PDFA_HEADER
    with _tempfile(suffix=".tex", text=header) as header_file:
        args = [pandoc, "-f", "markdown", "-t", "pdf", "-o", str(out_path), "-H", str(header_file)]
        _run_pandoc(args, markdown)
    if shutil.which(gs) is not None:
        _to_pdf_a(out_path, gs=gs)
    return out_path


def render_all(doc: MarDocument, out_dir: Path, *, pandoc: str = "pandoc", strict: bool = True) -> dict[str, Path]:
    """Render the MAR to every available format. Always writes ``mar.md``; adds ``mar.docx`` and ``mar.pdf``
    when Pandoc is installed. Returns the map of format -> path actually written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(doc, strict=strict)
    written: dict[str, Path] = {}
    md_path = out_dir / "mar.md"
    md_path.write_text(markdown, encoding="utf-8")
    written["md"] = md_path
    if pandoc_available(pandoc):
        written["docx"] = render_docx(markdown, out_dir / "mar.docx", pandoc=pandoc)
        try:
            written["pdf"] = render_pdf_a(markdown, out_dir / "mar.pdf", pandoc=pandoc)
        except RenderError:
            pass  # a LaTeX engine may be missing even when pandoc is present; DOCX + MD still delivered
    return written


# PDF/A intent for the LaTeX engine. pdfx with the a-2b option declares the conformance level and the
# required metadata/output intent; Ghostscript post-processing (when present) makes it authoritative.
_PDFA_HEADER = r"""
\usepackage[a-2b]{pdfx}
\hypersetup{pdfstartview=}
"""


def _run_pandoc(args: list[str], markdown: str) -> None:
    if not shutil.which(args[0]):
        raise RenderError(f"{args[0]} is not installed")
    try:
        proc = subprocess.run(args, input=markdown, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - environment failure
        raise RenderError(f"pandoc failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise RenderError(f"pandoc exited {proc.returncode}: {proc.stderr[-2000:]}")


def _to_pdf_a(pdf_path: Path, *, gs: str) -> None:  # pragma: no cover - requires ghostscript
    tmp = pdf_path.with_suffix(".pdfa.pdf")
    args = [gs, "-dPDFA=2", "-dBATCH", "-dNOPAUSE", "-sColorConversionStrategy=UseDeviceIndependentColor",
            "-sDEVICE=pdfwrite", "-dPDFACompatibilityPolicy=1", f"-sOutputFile={tmp}", str(pdf_path)]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=300, check=False)
    if proc.returncode == 0 and tmp.exists():
        tmp.replace(pdf_path)


class _tempfile:
    """Small context manager: a temp file seeded with text, cleaned up on exit."""

    def __init__(self, *, suffix: str, text: str):
        self.suffix = suffix
        self.text = text

    def __enter__(self) -> Path:
        import tempfile

        fd, name = tempfile.mkstemp(suffix=self.suffix)
        self.path = Path(name)
        with open(fd, "w", encoding="utf-8") as handle:
            handle.write(self.text)
        return self.path

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)
