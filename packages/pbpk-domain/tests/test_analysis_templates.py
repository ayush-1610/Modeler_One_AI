"""Analysis templates (T-31, D-26): the typed registry, and the VBE crossover's inputs the person must give."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pbpk_domain.analysis_templates import (
    AnalysisTemplate,
    check_inputs,
    list_templates,
    load_template,
    resolved_limits,
)

pytestmark = pytest.mark.req("T-31")

GOOD = {
    "test_formulation": "Test tablet", "reference_formulation": "RLD tablet",
    "variability": [{"parameter": "Gastric emptying time", "cv_percent": 20, "source": "Example crossover study 2019"}],
    "n_subjects": 24, "n_trials": 100, "seed": 7, "pos_threshold": 0.8,
}


def test_every_template_loads_and_is_a_draft_until_signed():
    templates = {t.id: t for t in list_templates()}
    assert {"ddi-cyp3a4-victim", "vbe-crossover"} <= set(templates)
    assert all(t.status == "DRAFT" for t in templates.values())


def test_the_vbe_decision_inputs_are_never_defaulted():
    vbe = load_template("vbe-crossover")
    for input_id in ("variability", "n_subjects", "n_trials", "seed", "pos_threshold"):
        spec = vbe.input(input_id)
        assert spec.never_default and spec.default is None
    problems = check_inputs(vbe, {})
    assert any("Intra-subject variability" in p and "never defaulted" in p for p in problems)
    assert any("Virtual trials" in p for p in problems)
    assert check_inputs(vbe, GOOD) == []


def test_a_variability_needs_its_source_and_a_positive_cv():
    vbe = load_template("vbe-crossover")
    no_source = {**GOOD, "variability": [{"parameter": "Gastric emptying time", "cv_percent": 20, "source": ""}]}
    assert any("its source is needed" in p for p in check_inputs(vbe, no_source))
    zero = {**GOOD, "variability": [{"parameter": "Gastric emptying time", "cv_percent": 0, "source": "x"}]}
    assert any("CV above 0" in p for p in check_inputs(vbe, zero))
    assert any("fraction in (0, 1]" in p for p in check_inputs(vbe, {**GOOD, "pos_threshold": 80}))
    assert any("unknown inputs: gastric" in p for p in check_inputs(vbe, {**GOOD, "gastric": 1}))


def test_the_standard_limits_are_the_default_and_the_nti_ones_await_verification():
    vbe = load_template("vbe-crossover")
    standard = resolved_limits(vbe, GOOD)
    assert (standard.lower, standard.upper, standard.ci_level, standard.verified) == (0.80, 1.25, 0.90, True)
    nti = resolved_limits(vbe, {**GOOD, "limits": "nti"})
    assert (nti.lower, nti.verified) == (0.90, False) and nti.source.startswith("[VERIFY]")


def test_the_schema_refuses_a_default_for_an_input_that_is_never_defaulted():
    doc = load_template("vbe-crossover").model_dump(by_alias=True)
    doc["inputs"] = [{**i, "default": 0.8} if i["id"] == "pos_threshold" else i for i in doc["inputs"]]
    with pytest.raises(ValidationError, match="never defaulted"):
        AnalysisTemplate.model_validate(doc)


@pytest.mark.req("T-31")
def test_the_observed_be_study_is_optional_but_complete_with_its_source_when_given():
    template = load_template("vbe-crossover")
    assert not template.input("observed_be").required and template.input("observed_be").never_default
    assert not any("Observed BE study" in p for p in check_inputs(template, {}))
    bad = {"observed_be": {"metrics": {"AUC_inf": {"gmr": 1.02, "between_subject_cv_percent": 25}}}}
    assert any("its source is needed" in p for p in check_inputs(template, bad))
    zero = {"observed_be": {"source": "study", "metrics": {"C_max": {"gmr": 0, "between_subject_cv_percent": 25}}}}
    assert any("C_max: gmr above 0 is needed" in p for p in check_inputs(template, zero))
