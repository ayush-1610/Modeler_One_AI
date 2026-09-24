"""End-to-end glue: the guided write API stages real campaign inputs, and the single-node runner consumes
them to completion, writing the monitor the read API serves — create → CPF → studies → prepare → run → monitor.

No Temporal, no Docker, no real engine: a stub engine echoes the uploaded profile as the simulated one, so the
tier gate passes on the staged observed PK. This proves prepare's outputs actually feed the runner.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi.testclient import TestClient

from modeler_api import write_api
from modeler_api.auth import get_verifier
from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_api.main import app
from modeler_contracts.runs import CampaignRequest, EngineJob, EngineManifest, OutputFile
from modeler_orchestrator.local_runner import run_campaign
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance

PROFILE = {"times": [30.0, 60.0, 120.0, 240.0, 480.0], "values": [40.0, 34.0, 19.0, 6.6, 0.4],
           "time_unit": "min", "unit": "µmol/l"}


def _claims():
    import time
    return {"sub": "u", "name": "Dev", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
            "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


class _Verifier:
    def verify(self, token):
        return _claims()


def _renal_cpf() -> dict:
    prov = Provenance(source_type="measured", reference="OSP Aciclovir")
    return CPF(compound="Renaldrug", parameters=(
        ParameterRecord(id="phys.mw", value=225.2, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=-1.6, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.pka.neutral", value=1.0, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="bind.fu", value=0.85, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=1.3, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
        # bound to PK-Sim's GFR process, or the pathway could not be placed and S0 refuses the CPF
        ParameterRecord(id="elim.renal.gfr_fraction", value=1.0, status=ParameterStatus.FIXED, provenance=prov,
                        engine_binding=EngineBinding(building_block="Compound", process="GlomerularFiltration",
                                                     parameter="GFR fraction", data_source="Literature")),
    )).model_dump(mode="json")


class EchoEngine:
    """Simulate → write the uploaded profile back as the engine's profiles.json (so the gate passes)."""

    def __call__(self, job: EngineJob) -> EngineManifest:
        out_dir = Path(unquote(urlparse(job.outputs_uri).path))
        out_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[OutputFile] = []
        if job.task == "simulate":
            p = out_dir / "profiles.json"
            p.write_text(json.dumps({"profiles": {"iv": {
                "times_min": PROFILE["times"], "concentrations": PROFILE["values"], "unit": PROFILE["unit"]}}}))
            outputs.append(OutputFile(name="profiles.json", uri=p.as_uri(),
                                      sha256=hashlib.sha256(p.read_bytes()).hexdigest(), size_bytes=p.stat().st_size))
        return EngineManifest(job_id=job.job_id, status="SUCCEEDED", engine_id="echo", image_digest="echo",
                              started_at="t0", finished_at="t1", inputs={}, outputs=outputs, warnings=[],
                              engine_info={}, stderr_tail="")


def test_guided_flow_stages_inputs_that_the_runner_completes(tmp_path):
    root = str(tmp_path)
    app.dependency_overrides[get_verifier] = lambda: _Verifier()
    app.dependency_overrides[write_api._stores] = lambda: (FileReadStore(root), FileWriteStore(root))
    try:
        c = TestClient(app)
        auth = {"Authorization": "Bearer tok"}
        c.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug", "question": "FIH"}, headers=auth)
        c.put("/api/v1/projects/renal-demo/compounds/Renaldrug/cpf", json=_renal_cpf(), headers=auth)
        study = {"study_id": "iv", "route": "iv_bolus", "dose_mg": 5.0, "infusion_time_min": 5.0,
                 "formulation": "solution", "food_state": "fasted", "profile": PROFILE}
        c.post("/api/v1/projects/renal-demo/studies", json={"studies": [study]}, headers=auth)
        prep = c.post("/api/v1/projects/renal-demo/questions/qoi-1/campaign:prepare",
                      json={"compound": "Renaldrug", "stages": ["S0", "S1"]}, headers=auth).json()["data"]
    finally:
        app.dependency_overrides.clear()

    # Feed prepare's staged inputs straight into the single-node runner.
    request = CampaignRequest(
        campaign_id="camp-int", tenant_id="t1", compound="Renaldrug", map_id=prep["map_id"],
        cpf_uri=prep["cpf_uri"], cpf_sha256=prep["cpf_sha256"], map_uri=prep["map_uri"],
        observed_uri=prep["observed_uri"], stages=["S0", "S1"], stage_budgets_seconds={"S1": 600},
    )
    outcome = run_campaign(request, read_root=root, project="renal-demo", question="FIH", engine=EchoEngine())

    assert outcome.status == "COMPLETED", outcome.reason
    campaign = FileReadStore(root).get_campaign("t1", "camp-int")
    assert campaign["status"] == "COMPLETED"
    assert next(s for s in campaign["stages"] if s["stage"] == "S1")["status"] == "PASSED"
