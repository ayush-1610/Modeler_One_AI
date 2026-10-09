"""S6 virtual bioequivalence (T-31 B6 PR 4): the MAP's vbe-crossover application on a scripted engine.

The engine here only writes files in PK-Sim's shapes (exported models, population.csv, pk_analyses.csv) so the
orchestration can be checked: two arms built from the CPF's formulations, the same individuals in both, each arm its
own occasion seed, and K trials judged. Its numbers are made up; real VBE evidence comes only from PK-Sim.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from modeler_contracts.runs import EngineJob, EngineManifest, OutputFile, RoundContext
from modeler_orchestrator.campaign_activities import exported_pkml_name
from modeler_orchestrator.vbe_activities import run_vbe
from pbpk_domain.campaign.map import MapApplication, generate_map
from pbpk_domain.campaign.split import FoodState, FormulationKind, QuestionOfInterest, Route, StudyRecord, split_studies
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

pytestmark = pytest.mark.req("T-31")
PROV = Provenance(source_type="measured", reference="test")
PLASMA = "Organism|PeripheralVenousBlood|Renaldrug|Plasma (Peripheral Venous Blood)"
INPUTS = {"test_formulation": "Test", "reference_formulation": "Ref", "n_subjects": 12, "n_trials": 4, "seed": 5,
          "pos_threshold": 0.8,
          "variability": [{"parameter": "Organism|Stomach|Gastric emptying time", "cv_percent": 20, "source": "cited"}]}


def _cpf() -> CPF:
    def r(pid, value, unit=None, **kw):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED, provenance=PROV, **kw)

    tablets = [r(f"form.{n}.{k}", v, u) for n in ("Test", "Ref")
               for k, v, u in (("type", "Weibull", None), ("weibull.t50", 30.0, "min"), ("weibull.shape", 0.6, None))]
    return CPF(compound="Renaldrug", parameters=(
        r("phys.mw", 225.2, "g/mol"), r("phys.logp", -1.6, "Log Units"), r("phys.pka.neutral", 1.0), r("bind.fu", 0.85),
        r("phys.solubility.ref", 1.3, "mg/ml"),
        r("elim.renal.gfr_fraction", 1.0, engine_binding=EngineBinding(
            building_block="Compound", process="GlomerularFiltration", parameter="GFR fraction", data_source="Literature")),
        *tablets))


def _ctx(tmp_path: Path, inputs: dict, *, route: Route = Route.ORAL) -> tuple[RoundContext, CPF, object]:
    cpf = _cpf()
    study = StudyRecord(study_id="rld-sd", n=24, design="SD", route=route, dose_mg=100.0,
                        formulation=FormulationKind.IR_TABLET if route is Route.ORAL else FormulationKind.SOLUTION,
                        formulation_name="Ref" if route is Route.ORAL else None, food_state=FoodState.FASTED,
                        n_timepoints=12, infusion_time_min=None if route is Route.ORAL else 5.0)
    doc = generate_map(compound="Renaldrug", cpf=cpf, studies=[study], split=split_studies([study], QuestionOfInterest()),
                       objective="VBE", context_of_use="generic tablet", food_effect_in_question=False,
                       model_risk=Rating.MEDIUM, engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"},
                       applications=(MapApplication.pinned("vbe-crossover", inputs),))
    (tmp_path / "cpf.json").write_text(cpf.model_dump_json(), encoding="utf-8")
    (tmp_path / "map.json").write_text(doc.model_dump_json(), encoding="utf-8")
    ctx = RoundContext(campaign_id="camp-vbe", tenant_id="t1", stage="S6", round_index=1,
                       cpf_uri=(tmp_path / "cpf.json").as_uri(), cpf_sha256="x", pending_action=None, seed=3,
                       map_uri=(tmp_path / "map.json").as_uri())
    return ctx, cpf, doc


def _file(out: Path, name: str, text: str) -> OutputFile:
    p = out / name
    p.write_text(text, encoding="utf-8")
    return OutputFile(name=name, uri=p.as_uri(), sha256=hashlib.sha256(p.read_bytes()).hexdigest(), size_bytes=p.stat().st_size)


class ScriptedEngine:
    """Writes PK-Sim-shaped outputs: TEST exposure 3 % above the reference, each occasion a seeded ±10 % wobble."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.jobs: list[EngineJob] = []
        self.fail_on = fail_on

    def __call__(self, job: EngineJob) -> EngineManifest:
        self.jobs.append(job)
        if self.fail_on and job.job_id.endswith(self.fail_on):
            raise RuntimeError("engine exited with status 1; stderr: parameter not found")
        out = Path(unquote(urlparse(job.outputs_uri).path))
        out.mkdir(parents=True, exist_ok=True)
        outputs = []
        if job.task == "simulate":
            snapshot = json.loads(Path(unquote(urlparse(job.inputs[0].uri).path)).read_text(encoding="utf-8"))
            for sim in snapshot["Simulations"]:
                outputs.append(_file(out, exported_pkml_name(sim["Name"]), f"<pkml {sim['Name']}>"))
        else:
            arm_test = job.job_id.endswith("-test")
            if arm_test:
                n = job.options["population"]["number_of_individuals"]
                people = "IndividualId,Organism|Weight\n" + "".join(f"{i},{60 + i % 30}\n" for i in range(n))
            else:
                people = Path(unquote(urlparse(job.inputs[1].uri).path)).read_text(encoding="utf-8")
            ids = [int(row["IndividualId"]) for row in csv.DictReader(io.StringIO(people))]
            outputs.append(_file(out, "population.csv", people))
            rng = random.Random(job.options["occasion_seed"])
            rows = ['"IndividualId","QuantityPath","Parameter","Value","Unit"']
            for i in ids:
                wobble = 1 + rng.uniform(-0.1, 0.1)
                for metric, base in (("AUC_inf", 500.0), ("C_max", 5.0)):
                    value = base * (1 + 0.02 * (i % 7)) * wobble * (1.03 if arm_test else 1.0)
                    rows.append(f'{i},"{PLASMA}","{metric}",{value},µmol/l')
            outputs.append(_file(out, "pk_analyses.csv", "\n".join(rows) + "\n"))
        return EngineManifest(job_id=job.job_id, status="SUCCEEDED", engine_id="scripted", image_digest="scripted",
                              started_at="t0", finished_at="t1", inputs={}, outputs=outputs, warnings=[],
                              engine_info={}, stderr_tail="")


def test_both_arms_run_the_same_individuals_on_their_own_occasions_and_k_trials_are_judged(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", (tmp_path / "objstore").as_uri())
    ctx, cpf, doc = _ctx(tmp_path, INPUTS)
    engine = ScriptedEngine()
    vbe = run_vbe(ctx, engine, cpf=cpf, map_doc=doc)

    assert vbe["status"] == "RUN", vbe.get("reason")
    simulate, test_arm, reference_arm = engine.jobs
    snapshot = json.loads(Path(unquote(urlparse(simulate.inputs[0].uri).path)).read_text(encoding="utf-8"))
    assert sorted(s["Name"] for s in snapshot["Simulations"]) == ["vbe-reference", "vbe-test"]
    used = {s["Name"]: json.dumps(s) for s in snapshot["Simulations"]}
    assert '"Test"' in used["vbe-test"] and '"Ref"' in used["vbe-reference"]  # each arm its product's formulation
    assert '"Ref"' not in used["vbe-test"] and '"Test"' not in used["vbe-reference"]
    assert test_arm.options["population"]["number_of_individuals"] == 48 and test_arm.options["seed"] == 5
    assert (test_arm.options["occasion_seed"], reference_arm.options["occasion_seed"]) == (11, 12)
    assert test_arm.options["variability"] == [{"path": "Organism|Stomach|Gastric emptying time", "cv_percent": 20}]
    people = next(i for i in reference_arm.inputs if i.name == "population.csv")
    assert people.uri.endswith("/s6/vbe/test/population.csv")  # the reference arm runs the TEST arm's individuals
    assert "population" not in reference_arm.options
    assert vbe["n_trials_run"] == 4 and vbe["individuals"] == 48 and vbe["design_study"] == "rld-sd"
    assert 1.0 < vbe["metrics"]["AUC_inf"]["gmr_median"] < 1.07 and vbe["meets_threshold"]
    assert vbe["limits"] == [0.80, 1.25] and vbe["limits_verified"] is True
    assert vbe["validation"]["status"] == "NOT_VALIDATED" and "no observed BE study" in vbe["validation"]["reason"]


def test_a_vbe_that_cannot_run_says_why_and_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", (tmp_path / "objstore").as_uri())
    ctx, cpf, doc = _ctx(tmp_path, {k: v for k, v in INPUTS.items() if k != "variability"})
    out = run_vbe(ctx, ScriptedEngine(), cpf=cpf, map_doc=doc)
    assert out["status"] == "NOT_RUN" and "never defaulted" in out["reason"]

    ctx, cpf, doc = _ctx(tmp_path, INPUTS)
    stopped = run_vbe(ctx, ScriptedEngine(fail_on="-test"), cpf=cpf, map_doc=doc)
    assert stopped["status"] == "NOT_RUN" and "parameter not found" in stopped["reason"]

    ctx, cpf, doc = _ctx(tmp_path, INPUTS, route=Route.IV_INFUSION)
    no_design = run_vbe(ctx, ScriptedEngine(), cpf=cpf, map_doc=doc)
    assert no_design["status"] == "NOT_RUN" and "no oral single-dose study" in no_design["reason"]

    plain = doc.model_copy(update={"applications": ()})
    assert run_vbe(ctx, ScriptedEngine(), cpf=cpf, map_doc=plain) is None


def test_the_s6_notes_state_the_vbe_result_or_why_it_did_not_run(tmp_path, monkeypatch):
    from modeler_orchestrator.local_runner import _vbe_note

    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", (tmp_path / "objstore").as_uri())
    ctx, cpf, doc = _ctx(tmp_path, INPUTS)
    note = _vbe_note(run_vbe(ctx, ScriptedEngine(), cpf=cpf, map_doc=doc))
    assert note.startswith("VBE (vbe-crossover ") and "4 virtual trials of 12" in note and "joint" in note
    assert "validation NOT_VALIDATED: no observed BE study" in note
    assert _vbe_note({"template": "vbe-crossover", "template_version": "0.1.0-draft", "status": "NOT_RUN",
                      "reason": "the engine stopped: x"}) == "VBE (vbe-crossover 0.1.0-draft) not run: the engine stopped: x"


def test_the_f304_gate_judges_the_model_against_the_observed_be_study(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", (tmp_path / "objstore").as_uri())
    ctx, cpf, doc = _ctx(tmp_path, INPUTS)
    simulated = run_vbe(ctx, ScriptedEngine(), cpf=cpf, map_doc=doc)["metrics"]["AUC_inf"]
    cv, mid = simulated["between_subject_cv_percent"], simulated["gmr_median"]
    observed = {"source": "Client BE study 2021 (reference arm n=24)",
                "metrics": {"AUC_inf": {"gmr": mid, "between_subject_cv_percent": cv * 1.2}}}
    ctx, cpf, doc = _ctx(tmp_path, {**INPUTS, "observed_be": observed})
    passed = run_vbe(ctx, ScriptedEngine(), cpf=cpf, map_doc=doc)["validation"]
    assert passed["status"] == "PASSED" and passed["cv_fold"] == 1.5 and passed["criterion_verified"] is False
    assert {c["check"] for c in passed["checks"]} == {"between_subject_cv", "observed_gmr_within_simulated_5_95"}
    far = {**observed, "metrics": {"AUC_inf": {"gmr": 1.4, "between_subject_cv_percent": cv * 3}}}
    ctx, cpf, doc = _ctx(tmp_path, {**INPUTS, "observed_be": far})
    failed = run_vbe(ctx, ScriptedEngine(), cpf=cpf, map_doc=doc)["validation"]
    assert failed["status"] == "FAILED"
    assert "AUC_inf between_subject_cv" in failed["reason"] and "AUC_inf observed_gmr_within_simulated_5_95" in failed["reason"]
