"""T-54: the MAR's model development history comes from the campaign's change ledger."""

from __future__ import annotations

import pytest

from pbpk_domain.report.campaign_mar import assemble_campaign_mar
from pbpk_domain.report.mar import check_report, render_markdown

from .test_map import _cpf, _map

_LEDGER = {"entries": [
    {"seq": 1, "stage": "S2", "kind": "fit", "reason": "round 2: fit phys.logp", "cpf_before": "a", "cpf_after": "b",
     "changes": [{"parameter": "phys.logp", "before": 2.6, "after": 3.1, "unit": "Log Units", "status": "FITTED",
                  "fitted_at_stage": "S2"}],
     "verdicts": [{"study_id": "po_low", "stage": "S2", "before": "fail", "after": "pass"},
                  {"study_id": "iv", "stage": "S1", "before": "pass", "after": "fail"}]},
    {"seq": 2, "stage": "S2", "kind": "joint refit", "reason": "joint fit kept", "cpf_before": "b", "cpf_after": "c",
     "changes": [], "note": "the CPFs are not readable here; parameter changes not listed", "verdicts": []},
]}


@pytest.mark.req("T-54")
def test_the_mar_lists_the_development_history_and_the_joint_stage():
    evidence = {"S1": {"status": "PASSED"}, "S2": {"status": "PASSED"}, "SJ": {"status": "PASSED", "rounds": []}}
    mar = assemble_campaign_mar(map_doc=_map(), final_cpf=_cpf(), stage_evidence=evidence, history=_LEDGER)
    development = next(s for s in mar.sections if s.number == "4")
    assert [s.heading for s in development.subsections][-2:] == ["SJ — Joint refinement", "Model development history"]
    table = next(t for t in mar.evidence.tables if t.id == "development_history")
    assert table.rows[0][3] == "phys.logp 2.6 → 3.1 Log Units" and table.rows[0][4] == "po_low fail → pass; iv pass → fail"
    assert table.rows[1][3].startswith("the CPFs are not readable") and table.rows[1][4] == "none"
    assert not check_report(mar) and "Model development history" in render_markdown(mar)

    plain = assemble_campaign_mar(map_doc=_map(), final_cpf=_cpf(), stage_evidence={"S1": {"status": "PASSED"}})
    assert [s.heading for s in next(s for s in plain.sections if s.number == "4").subsections][-1].startswith("S3")
