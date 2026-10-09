"""The MAP carries the applications its question pins (T-31 B6 PR 2): pinned template, the person's inputs, and no
signature while a never-defaulted input is missing."""

from __future__ import annotations

import hashlib
import json

import pytest

from pbpk_domain.analysis_templates import load_template
from pbpk_domain.campaign.map import MapApplication
from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance

from .test_map import _cpf, _map

pytestmark = pytest.mark.req("T-31")

COMPLETE = {
    "test_formulation": "Test", "reference_formulation": "Ref",
    "variability": [{"parameter": "Organism|Stomach|Gastric emptying time", "cv_percent": 30, "source": "cited study"}],
    "n_subjects": 24, "n_trials": 100, "seed": 7, "pos_threshold": 0.8,
}


def _with_tablets() -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")
    forms = tuple(ParameterRecord(id=f"form.{name}.weibull.t50", value=t50, unit="min", status=ParameterStatus.FIXED,
                                  provenance=prov) for name, t50 in (("Test", 25.0), ("Ref", 30.0)))
    base = _cpf()
    return base.model_copy(update={"parameters": (*base.parameters, *forms)})


def test_a_map_with_no_application_hashes_as_before():
    # signatures given before applications existed bind a hash without the field: it stays the same
    m = _map()
    before = m.model_dump(mode="json", exclude={"status", "signature", "applications"})
    assert m.content_sha256() == hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert _map(applications=(MapApplication.pinned("vbe-crossover", COMPLETE),)).content_sha256() != m.content_sha256()


def test_an_application_is_pinned_at_the_registry_version():
    app = MapApplication.pinned("vbe-crossover")
    assert app.template_version == load_template("vbe-crossover").version
    with pytest.raises(KeyError):
        MapApplication.pinned("no-such-template")
    moved = app.model_copy(update={"template_version": "0.0.1"})
    assert moved.problems() == [f"vbe-crossover: the MAP pins version 0.0.1, the registry has {app.template_version}"]


def test_a_missing_never_defaulted_input_is_named_and_blocks_the_signature():
    m = _map(applications=(MapApplication.pinned("vbe-crossover"),))
    problems = m.application_problems()
    assert any("Intra-subject variability" in p and "never defaulted" in p for p in problems)
    assert any("Virtual trials" in p for p in problems)
    with pytest.raises(ValueError, match="applications are incomplete"):
        m.sign(printed_name="Dr Lead")


def test_complete_inputs_sign_and_formulations_are_checked_against_the_cpf():
    cpf = _with_tablets()
    app = MapApplication.pinned("vbe-crossover", COMPLETE)
    assert app.problems(cpf) == []
    signed = _map(cpf=cpf, applications=(app,)).sign(printed_name="Dr Lead")
    assert signed.signature.content_sha256 == signed.content_sha256()
    wrong = MapApplication.pinned("vbe-crossover", {**COMPLETE, "reference_formulation": "RLD tablet"})
    assert wrong.problems(cpf) == [("vbe-crossover: Reference (RLD) formulation (a CPF formulation): 'RLD tablet' is not "
                                    "a CPF formulation (Test, Ref)")]
