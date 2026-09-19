from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pbpk_domain.m15 import AssessmentTable, RatedElement, Rating
from pbpk_domain.report import (
    Evidence,
    FigureRef,
    MarDocument,
    MarSection,
    MarSignature,
    ReportError,
    TableRef,
    ValueRef,
    assemble_mar,
    check_report,
    render_markdown,
)
from pbpk_domain.report.mar import format_number


def _metrics() -> dict:
    return {
        "studies": [
            {"study_id": "iv", "role": "fitting", "predicted_auc": 100.0, "observed_auc": 98.0,
             "predicted_cmax": 10.0, "observed_cmax": 10.5, "predicted_tmax": 1.0, "observed_tmax": 1.0,
             "predicted_thalf": 5.0, "observed_thalf": 5.0, "auc_in_limits": True, "cmax_in_limits": True},
        ],
        "AUC": {"n": 1, "gmfe": 1.0204, "fraction_within_2fold": 1.0},
        "Cmax": {"n": 1, "gmfe": 1.05, "fraction_within_2fold": 1.0},
        "tier": "medium", "ruleset": "acc@1",
        "groups": [{"role": "fitting", "quantity": "AUC", "n": 1, "fraction_within": 1.0,
                    "required_fraction": 0.9, "passes": True}],
    }


def _params() -> TableRef:
    return TableRef(id="parameters", title="Compound parameter framework",
                    columns=("Parameter", "Value", "Unit", "Status", "Source"),
                    rows=(("phys.logp", "2.5", "Log Units", "fitted", "ParameterIdentification"),),
                    source="final CPF Drug-A@4")


def _mar(**overrides) -> MarDocument:
    kwargs = dict(
        compound="Drug-A",
        question_of_interest="Predict the fed/fasted exposure ratio.",
        context_of_use="Waive a dedicated food-effect study.",
        model_risk=Rating.MEDIUM,
        parameters=_params(),
        stage_assessments=[("S2", _metrics())],
        m15_tables=(),
        generated_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    kwargs.update(overrides)
    return assemble_mar(**kwargs)


# --- formatting ----------------------------------------------------------------------------------


def test_format_number_uses_significant_figures_and_ints():
    assert format_number(1.0204) == "1.02"
    assert format_number(5.0) == "5"
    assert format_number(100) == "100"
    assert format_number("medium") == "medium"


def test_value_ref_appends_unit():
    assert ValueRef(id="x", value=95.0, unit="%", source="s").rendered() == "95%"
    assert ValueRef(id="y", value=50.3, unit="ng/mL", source="s").rendered() == "50.3 ng/mL"


# --- assembly + evidence -------------------------------------------------------------------------


@pytest.mark.req("T-24")
def test_assembled_report_has_no_bare_numbers_and_resolves():
    doc = _mar()
    # the acceptance invariant: every number is a reference, every reference resolves
    assert check_report(doc) == []
    # evidence derived from the metrics
    assert doc.evidence.value("auc_gmfe_s2").value == 1.0204
    assert doc.evidence.value("auc_within2fold_s2").value == 100.0
    assert doc.evidence.value("acceptance_tier").value == "medium"
    assert doc.evidence.table("pk_s2") is not None


def test_render_resolves_references_and_numbers_appear():
    md = render_markdown(_mar())
    assert "geometric mean fold error is 1.02" in md
    assert "100% of predictions within 2-fold" in md
    assert "**Table" in md and "Compound parameter framework" in md
    assert "## Evidence index" in md
    assert "value:auc_gmfe_s2" in md  # the index lists every value


# --- the linter (T-24 acceptance) ----------------------------------------------------------------


def test_bare_number_in_prose_is_rejected():
    doc = MarDocument(
        compound="D", title="t", question_of_interest="q", context_of_use="c", model_risk=Rating.LOW,
        sections=(MarSection(number="1", heading="h", body="The GMFE was 1.3 which is acceptable."),),
        evidence=Evidence(),
    )
    issues = check_report(doc)
    assert any(i.kind == "unreferenced_number" and "1.3" in i.detail for i in issues)
    with pytest.raises(ReportError):
        render_markdown(doc, strict=True)


def test_unresolved_reference_is_rejected():
    doc = MarDocument(
        compound="D", title="t", question_of_interest="q", context_of_use="c", model_risk=Rating.LOW,
        sections=(MarSection(number="1", heading="h", body="The AUC GMFE is {{value:missing}}."),),
        evidence=Evidence(),
    )
    issues = check_report(doc)
    assert any(i.kind == "unresolved_reference" and "missing" in i.detail for i in issues)
    with pytest.raises(ReportError):
        render_markdown(doc, strict=True)


def test_verbatim_section_is_exempt_from_the_number_linter():
    # the quoted objective may legitimately contain numbers (e.g. "400 mg")
    doc = MarDocument(
        compound="D", title="t", question_of_interest="q", context_of_use="c", model_risk=Rating.LOW,
        sections=(MarSection(number="1", heading="Objective", body="Predict exposure at 400 mg.", verbatim=True),),
        evidence=Evidence(),
    )
    assert check_report(doc) == []
    assert "400 mg" in render_markdown(doc, strict=True)


# --- figures, M15 tables, signatures -------------------------------------------------------------


def test_figure_reference_renders_image_and_number():
    fig = FigureRef(id="gof_s2", title="Goodness of fit, stage S2", path="figures/gof_s2.png",
                    caption="Predicted vs observed.", source="evaluate_round S2")
    md = render_markdown(_mar(figures=(fig,)))
    assert "![Goodness of fit, stage S2](figures/gof_s2.png)" in md
    assert "**Figure 1. Goodness of fit, stage S2.**" in md


def test_m15_tables_and_signatures_render():
    table = AssessmentTable(
        question_of_interest="Food effect", context_of_use="waiver",
        model_influence=RatedElement(description="high influence", rating=Rating.HIGH, justification="drives decision"),
        model_risk=RatedElement(description="medium", rating=Rating.MEDIUM, justification="balanced"),
    )
    sig = MarSignature(printed_name="Dr Lead", meaning="Approved", signed_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
                       signature_id="sig-1")
    md = render_markdown(_mar(m15_tables=(table,), signatures=(sig,)))
    assert "## ICH M15 assessment tables" in md
    assert "model influence" in md and "high influence" in md
    assert "## Signatures" in md
    assert "Dr Lead | Approved | 2026-09-19" in md


def test_unused_evidence_flagged_only_when_requested():
    doc = _mar()
    extra = doc.model_copy(update={"evidence": doc.evidence.model_copy(update={
        "values": (*doc.evidence.values, ValueRef(id="orphan", value=1.0, source="s"))})})
    assert check_report(extra) == []  # default: unused evidence is fine
    issues = check_report(extra, require_all_evidence_used=True)
    assert any(i.kind == "unused_evidence" and "orphan" in i.detail for i in issues)


# --- rendering to files (Pandoc-gated) -----------------------------------------------------------


def test_render_all_always_writes_markdown(tmp_path):
    from pbpk_domain.report import render as render_mod

    written = render_mod.render_all(_mar(), tmp_path)
    assert "md" in written and written["md"].exists()
    assert "Modeling Analysis Report" in written["md"].read_text(encoding="utf-8")
    # DOCX/PDF appear only when pandoc is installed
    if render_mod.pandoc_available():
        assert written["docx"].exists()
    else:
        assert "docx" not in written
