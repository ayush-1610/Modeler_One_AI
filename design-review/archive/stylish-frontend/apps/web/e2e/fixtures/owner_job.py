"""The owner's job on Inputs, its own small delivery (plan docs/plans/2026-11-14-inputs-task-first.md §2.2.7): software
test data for the browser flow, which runs with no LLM provider. Made-up numbers of the made-up Exampleamide: it proves
the review path, never a model.

    uv run python owner_job.py <read root> <project id> <out dir>

Writes four workbooks to <out dir>, the individual ones laid out like the 230-23 BE arms of er_be_workbooks.py (times
across, BLQ in the pre-dose column, an LLOQ footnote; no Mean / SD rows, so every number of a table is read):
- `OJ-101 plasma means.xlsx`: the study's mean profile under "Study OJ-101: mean plasma concentrations of Exampleamide
  (ng/mL), 50 mg, fasting", the one file that names the study, so the delivery has a study to sign; and, far below the
  table, a working note with a number in it (a number outside every table and its context: "numbers not read"). Its
  table's layout was signed off earlier: the rules' own spec for it is put in the project's mapping cache as a person's
  version, approved (as delivery.py does with the truth specs), so it is read with it.
- `OJ-101 Reference.xlsx`, `OJ-101 Test.xlsx`: the study's two arms, each six subjects in periods I and II with the same
  labels (001 · I, 002 · II, ...). Their titles name OJ-101, but the delivery reads no study of them (the rules' study id
  of a file named "... Reference" is the sheet form's OJ-101-REF, which its title does not state), so their values wait
  to be linked; linked to one study in one arm, their subjects and periods collide.
- `lab-export-0412.xlsx`: the same layout under a title that names no study (another dose, fed).
The three individual tables share one layout, which the rules read and no person approved: the one layout that waits.
No file states the study's route, its number of subjects, its dosage form or what it is for.

Prints, as JSON, the file names and the layout signed off earlier.
"""

from __future__ import annotations

import io
import json
import math
import sys
from pathlib import Path

from openpyxl import Workbook

from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.mapping.rules import map_by_rule
from modeler_intake.source import parse_document, region_grid
from modeler_project import FileProjectStore, Workspace
from modeler_project.mapping_cache import MappingCache

DRUG = "Exampleamide"
STUDY = "OJ-101"
MEANS = f"{STUDY} plasma means.xlsx"
ARMS = (("Reference", 160.0), ("Test", 150.0))
STRAY = "Note: 2 samples were re-assayed on day 14"
TIMES = ["Pre-dose", "1.00", "2.00", "4.00", "6.00", "8.00", "12.00", "24.00"]


def curve(t: float, scale: float) -> float:
    return round(scale * (math.exp(-0.06 * t) - math.exp(-0.35 * t)), 2)


def saved(wb: Workbook) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def individual(title: str, scale: float) -> bytes:
    """A title line, then six subjects in periods I and II, times across (as er_be_workbooks.py), the LLOQ under them."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([title])
    ws.append([])
    ws.append(["Time (hr)"])
    ws.append(["Subject No.", "Period", *TIMES])
    for i in range(1, 7):
        ws.append([f"{i:03d}", "I" if i % 2 else "II", "BLQ", *(curve(float(t), scale * (0.85 + 0.05 * i)) for t in TIMES[1:])])
    ws.append([])
    ws.append(["BLQ = below the lower limit of quantification (0.50 ng/mL)"])
    return saved(wb)


def means() -> bytes:
    """The mean profile with its SD and N per time and the LLOQ under it, and the stray note well below the table's
    context lines."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Means"
    ws.append([f"Study {STUDY}: mean plasma concentrations of {DRUG} (ng/mL), 50 mg, fasting"])
    ws.append(["Time (h)", "Mean concentration (ng/mL)", "SD", "N"])
    for t, v in ((1, 60.0), (2, 110.0), (4, 150.0), (8, 90.0), (12, 50.0), (24, 12.0)):
        ws.append([t, v, round(v / 5, 1), 12])
    ws.append([])
    ws.append(["LLOQ = 0.5 ng/mL"])
    ws["A19"] = STRAY
    return saved(wb)


root, project_id, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
files = {
    MEANS: means(),
    **{f"{STUDY} {arm}.xlsx": individual(f"Study {STUDY}: plasma concentrations of {DRUG} (ng/mL), {arm}, 50 mg, fasting", scale)
       for arm, scale in ARMS},
    "lab-export-0412.xlsx": individual(f"Plasma concentrations of {DRUG} (ng/mL), 25 mg, fed", 80.0),
}
for name, data in files.items():
    (out / name).write_bytes(data)

# the means table's layout, signed off by a person earlier: the rules' spec for it, approved in the project's cache
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
cache = MappingCache(Workspace(FileProjectStore(root), tenant, project_id))
doc = parse_document(files[MEANS], MEANS)
(region,) = [r for r in doc.regions if r.kind == "table"]
grid = region_grid(doc, region.id)
rule = map_by_rule(grid, region, filename=MEANS, drug=DRUG, document_role=doc.role)
if rule is None:
    raise SystemExit(f"no rule reads the table of {MEANS}")
entry = cache.propose(layout_fingerprint(grid), rule.spec, origin="person", origin_detail="e2e-fixture",
                      first_seen=(doc.file_sha256, region.id), by="e2e-fixture")
cache.approve(entry.mapping_id, entry.version, by="e2e-fixture", note="signed off earlier")
print(json.dumps({"files": sorted(files), "study": STUDY, "stray": STRAY,
                  "approved": {"mapping_id": entry.mapping_id, "version": entry.version, "where": region.where}}))
