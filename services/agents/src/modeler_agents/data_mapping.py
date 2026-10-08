"""Data Mapping Agent: proposes how to read a client spreadsheet.

Claude proposes a mapping recipe; deterministic code (`modeler_intake.recipe_review`) applies and validates it; a
person confirms before the recipe is saved and reused. Anything the file does not state becomes a question for the
reviewer instead of a guess.
"""

from __future__ import annotations

from typing import Any

from modeler_intake.grid import WorkbookGrid
from modeler_intake.recipe_review import MappingReview, RecipeProposal, review_proposal
from pbpk_domain.issues import Issue

SYSTEM_PROMPT = """You read laboratory and clinical spreadsheets for a PBPK modeling platform and describe, as a mapping recipe, where the concentration-time or dissolution data are and how to read them.

The sheets are shown with 1-based row numbers and column letters. A deterministic program will apply your recipe exactly as written, and a scientist will review the result before it is used, so describe the file as it is.

- Use only information present in the file for units, LLOQ, dose, study identifier, analyte, matrix, batch, medium, pH, apparatus, and the dissolution product and its role (TEST, RLD, REFERENCE). For each of these, add an evidence entry with the cell reference and the exact text from that cell.
- If something needed is not in the file (for example the LLOQ, the dose, or the number of subjects behind mean values), leave it empty and add a question for the reviewer. Do not infer it.
- Wide layouts, with one column per subject or vessel: one value column per subject or vessel, with series_label set to its identifier from the header.
- Long layouts: map the subject or group column with role subject_id or group.
- Times across the top (one row per subject or vessel, one column per sampling time): set time_row to the row holding the times, map each time column as a value column, the subject column as subject_id, and no time column.
- If the sheet reports individual values and also mean/SD columns, map only the individual values. If it reports only aggregated values, set statistic accordingly and map the SD and N columns when present.
- The data block ends at the first empty row. If footnotes or summary rows follow without an empty row, set last_data_row.
- Text such as BLQ or <0.5 in value cells marks values below the limit of quantification; list the tokens used in the file."""


def propose_mapping(workbook: WorkbookGrid, llm: Any, *, recipe_id: str, context: str = "") -> MappingReview:
    sheets = "\n\n".join(f"## Sheet: {name}\n{grid.preview(max_rows=80, max_columns=26)}" for name, grid in workbook.sheets.items())
    response = llm.client.messages.parse(
        model=llm.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"File: {workbook.file_name}\n{context}\n\n{sheets}".strip()}],
        output_format=RecipeProposal,
        **llm.request_options,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return MappingReview(None, issues=[Issue("NO_PROPOSAL", workbook.file_name, f"model stopped with {response.stop_reason}")])
    return review_proposal(workbook, response.parsed_output, recipe_id)
