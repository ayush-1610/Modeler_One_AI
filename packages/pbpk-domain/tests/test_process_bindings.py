"""T-49: a process parameter's PK-Sim candidates come from the harvested table; ValueOrigin carries harvested values."""

from __future__ import annotations

import pytest

from pbpk_domain.cpf.build import _origin
from pbpk_domain.cpf.models import ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.cpf.process_bindings import binding_candidates
from pbpk_domain.snapshot.models import ValueOrigin

pytestmark = pytest.mark.req("T-49")


def test_candidates_come_from_the_harvested_process_table():
    assert [(c.process, c.parameter, c.unit) for c in binding_candidates("elim.renal.gfr_fraction")] == [
        ("GlomerularFiltration", "GFR fraction", None)]
    assert [c.parameter for c in binding_candidates("elim.hepatic.total.plasma_clearance")] == ["Plasma clearance"]
    clspec = binding_candidates("elim.hepatic.CYP3A4.clspec")
    assert {c.process for c in clspec} == {"MetabolizationSpecific_FirstOrder", "rCYP450_FirstOrder"}
    assert all(c.molecule == "CYP3A4" and c.unit == "l/µmol/min" for c in clspec)
    assert clspec[0].binding("Literature").process.endswith(":CYP3A4")
    assert binding_candidates("elim.hepatic.CYP3A4.unknown_quantity") == []
    assert {c.process for c in binding_candidates("transp.OATP1B1.km")} >= {"ActiveTransportSpecific_MM"}


def test_value_origin_keeps_harvested_methods_only_and_the_builder_writes_them():
    assert ValueOrigin(source="Publication", method="InVitro").method == "InVitro"
    assert ValueOrigin(source="Publication", method="in vitro (HLM)").method is None
    record = ParameterRecord(id="phys.logp", value=1.2, unit="Log Units", status=ParameterStatus.FIXED,
                             provenance=Provenance(source_type="Publication", reference="Doe 2019", method="InVitro"))
    origin = _origin(record).to_json_dict()
    assert origin == {"Source": "Publication", "Method": "InVitro", "Description": "Doe 2019"}
    no_method = _origin(record.model_copy(update={"provenance": Provenance(source_type="Publication")})).to_json_dict()
    assert "Method" not in no_method
