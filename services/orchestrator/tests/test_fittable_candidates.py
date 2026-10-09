"""Only propose fit candidates this CPF can actually fit (moved from pbpk-domain's CPF tests in phase 8c, so the domain's
tests no longer reach into the orchestrator)."""

from __future__ import annotations

from modeler_orchestrator.campaign_activities import _fittable_candidates
from pbpk_domain.cpf.models import CPF, EngineBinding, FitPolicy, ParameterRecord, ParameterStatus, Provenance


def test_fit_candidates_are_filtered_to_what_the_cpf_can_fit():
    """A hepatic-enzyme candidate on a renally cleared compound resolves to nothing, so offering it would
    burn a round on a no-op and can exhaust the budget before the candidate that works is tried."""
    prov = Provenance(source_type="measured", reference="x")
    cpf = CPF(compound="Renal", parameters=(
        ParameterRecord(id="phys.mw", value=225.2, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=-1.5, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=-3.0, upper=0.0)),
        ParameterRecord(id="bind.fu", value=0.85, status=ParameterStatus.FIXED, provenance=prov),  # no bounds
        ParameterRecord(id="phys.solubility.ref", value=1.3, unit="mg/ml", status=ParameterStatus.FIXED,
                        provenance=prov, fit_policy=FitPolicy(stage=("S2",), lower=1.3, upper=130.0)),
        ParameterRecord(id="elim.renal.gfr_fraction", value=1.0, status=ParameterStatus.FIXED, provenance=prov,
                        engine_binding=EngineBinding(building_block="Compound", parameter="GFR fraction",
                                                     process="GlomerularFiltration", data_source="Literature"),
                        fit_policy=FitPolicy(stage=("S1",), lower=0.0, upper=3.0)),
    ))
    candidates = ("elim.hepatic.{enzyme}.clspec", "phys.logp", "elim.renal.gfr_fraction",
                  "perm.cellular", "bind.fu", "phys.solubility.ref")

    usable = _fittable_candidates(cpf, candidates, "S1")

    assert "elim.renal.gfr_fraction" in usable and "phys.logp" in usable
    assert "elim.hepatic.{enzyme}.clspec" not in usable   # no such parameter in this CPF
    assert "perm.cellular" not in usable                  # absent
    assert "bind.fu" not in usable                        # present but has no bounds to fit within
    assert "phys.solubility.ref" not in usable            # fittable, but only at S2
