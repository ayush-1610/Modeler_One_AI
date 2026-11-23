"""The structured sources' part in the browser flows, which run with no network to PubChem, openFDA or ChEMBL (build
B, plan 2026-11-05 §3.3): software test data.

    uv run python compound_sources.py <read root> <project>

Runs the real sources job (`modeler_api.compound_jobs.run_sources_job`: the stored pages, code's proposals, the run's
record, the inputs refreshed) with the services answering from the recorded answers for the invented Exampleamide
(`modeler_agents.evals.structured_answers`), so what the page shows is what a reading of the live services produces.
"""

from __future__ import annotations

import sys
from pathlib import Path

from modeler_agents.evals import structured_answers
from modeler_api import agent_jobs
from modeler_api.compound_jobs import run_sources_job
from modeler_project import FileProjectStore

root, project_id = Path(sys.argv[1]), sys.argv[2]
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
agent_jobs.structured_clients = structured_answers.clients   # the recorded answers, not the network
result = run_sources_job(FileProjectStore(root), tenant, project_id)
print(result["run_id"], result["proposed"])
