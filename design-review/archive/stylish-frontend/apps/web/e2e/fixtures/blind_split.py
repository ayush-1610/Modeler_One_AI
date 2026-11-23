"""Five literature studies of the made-up Exampleamide proposed and the inputs assembled, so that, with the project's
blinding on and no plan, the MS-01 split proposes a role for every study of the catalog and some for S5 (external
validation): a study that joins the catalog later (a signature that lands its dataset, a sheet form's group confirmed)
can be proposed for S5 too, and is then blinded (final review round 5). Software test data, never a model.

    uv run python blind_split.py <read root> <project id>

Prints, as JSON, the roles the split proposes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from modeler_project import FileProjectStore, Workspace
from modeler_project.dataset_register import propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.inputs import assemble
from modeler_project.roles import proposed_roles

root, project_id = Path(sys.argv[1]), sys.argv[2]
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
ws = Workspace(FileProjectStore(root), tenant, project_id)
for sid, route, dose in (("iv-250", "iv_infusion", 250), ("iv-500", "iv_infusion", 500), ("po-10", "oral", 10),
                         ("po-50", "oral", 50), ("po-100", "oral", 100)):
    propose_dataset(ws, ObservedDataset(
        id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, time_unit="h", unit="µmol/l",
        demographics_choice="healthy_adult_default",
        study={"study_id": sid, "n": 12, "route": route, "dose_mg": dose, "formulation": "solution", "food_state": "fasted",
               "n_timepoints": 5, **({"infusion_time_min": 60} if route == "iv_infusion" else {})},
        series=(Series(times=(0.5, 1, 2, 4, 8), values=(20.0, 35.0, 21.0, 9.0, 2.0), n=12),)), actor="e2e-fixture")
assemble(ws, by="e2e-fixture")
print(json.dumps({"roles": proposed_roles(ws)}))
