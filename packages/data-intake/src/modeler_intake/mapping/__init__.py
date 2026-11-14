"""The mapper (docs/plans/2026-11-12-intake-contracts.md §6.2, build D3): a typed mapping per table, executed by code.

A table region is read under a `MappingSpec` (mapping spec v2): rules and the mapping cache propose it first, the LLM
only for the rest, and the LLM never sees a number of the table's body (`redact`). Code reads every value:
- `fingerprint`: the layout fingerprint a cached spec is looked up by, and the header band the mapper is shown;
- `validate`: a spec checked against one region's grid and context (every constant and unit re-read from it);
- `execute`: the spec executed over the grid, every non-empty cell accounted for (`ExtractResult.cell_use`);
- `rules`: today's no-AI reading (`sheet_form.suggest`) and the client-data template turned into v2 specs;
- `redact`: what the table mapper is shown of a table, every body digit redacted;
- `prose_check`: the strict check a quoted prose fact passes before it is kept (code's number, never the model's).

The modules import down only (`reading` <- `validate` <- `execute`), so import them by name.
"""
