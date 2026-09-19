"""Report generation (task T-24): the Modeling Analysis Report (MAR, ICH M15 Appendix 2).

The MAR is assembled from campaign artifacts as a structured document whose prose carries no bare
numbers — every value, table and figure is a reference resolved from an evidence set at render time,
so nothing in the report can be stated that is not traceable to a computed artifact. ``render_markdown``
produces the reviewable document; ``report.render`` converts it to DOCX and PDF/A via Pandoc.
"""

from pbpk_domain.report.mar import (
    Evidence,
    FigureRef,
    MarDocument,
    MarSection,
    MarSignature,
    ReportError,
    ReportIssue,
    TableRef,
    ValueRef,
    assemble_mar,
    check_report,
    render_markdown,
)

__all__ = [
    "Evidence",
    "FigureRef",
    "MarDocument",
    "MarSection",
    "MarSignature",
    "ReportError",
    "ReportIssue",
    "TableRef",
    "ValueRef",
    "assemble_mar",
    "check_report",
    "render_markdown",
]
