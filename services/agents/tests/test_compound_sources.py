"""Build B (plan 2026-11-05 §3.3): the compound's values from PubChem, the FDA label and ChEMBL, read by code at the
project's start. The services answer from recorded answers for an invented compound (software test data, in the shapes
the services document; never a real drug's values)."""

from __future__ import annotations

import pytest

from modeler_agents.compound_sources import _binding_sentence, read_compound_sources
from modeler_agents.evals import structured_answers as answers
from modeler_agents.sources import SourceError
from modeler_project import FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import SourceType
from modeler_project.evidence_register import items
from modeler_project.requirements import derive, literature_items

pytestmark = pytest.mark.req("T-22")


def _read(tmp_path, **kwargs):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    pubchem, openfda, chembl = answers.clients(**kwargs)
    requirements = literature_items(derive(empty_brief(answers.DRUG, by="u")))
    outcome = read_compound_sources(ws, DocumentLibrary(ws), requirements, drug=answers.DRUG, actor="agent:sources",
                                    pubchem=pubchem, openfda=openfda, chembl=chembl)
    return ws, outcome


def test_each_source_gives_what_it_states_plainly_each_value_quoted_and_graded(tmp_path):
    ws, outcome = _read(tmp_path)
    assert [(s["name"], s["ok"], s["values"]) for s in outcome.sources] == [
        ("PubChem", True, 5), ("FDA label", True, 1), ("ChEMBL", True, 2)]
    got = {(e.target, e.value): e for e in items(ws)}
    mw = got[("phys.mw", 393.9)]
    assert mw.source_type is SourceType.DATABASE and mw.quote == '"MolecularWeight": "393.9"' and mw.confidence == "B"
    assert mw.source.title == f"PubChem compound {answers.CID} ({answers.DRUG})" and mw.source.url.endswith(str(answers.CID))
    xlogp = got[("phys.logp", 2.4)]
    assert xlogp.source_type is SourceType.PREDICTED and xlogp.confidence == "C" and xlogp.req_id == "REQ-phys.logp"
    measured = got[("phys.logp", 2.1)]
    assert measured.confidence == "B" and "Invented A" in measured.quote and measured.quote.startswith("LogP: log Kow = 2.1")
    assert got[("phys.logp", 2.9)].confidence == "C"                       # "(est)": predicted, whoever reports it
    solubility = got[("phys.solubility.ref", 1500.0)]
    assert solubility.value_pksim == pytest.approx(1.5) and solubility.unit_pksim == "mg/ml"
    assert solubility.conditions["temperature"] == "25 °C" and "read as 1500" in solubility.note
    fu = got[("bind.fu", 85.0)]
    assert fu.unit == "% bound" and fu.value_pksim == pytest.approx(0.15) and fu.source_type is SourceType.REGULATORY_REVIEW
    assert fu.quote == "Distribution Exampleamide is approximately 85% bound to human plasma proteins."
    assert "EXAMPLIX (NDA000001)" in fu.source.title and fu.source.locator == "§12.3 Pharmacokinetics"   # the innovator's
    acid, base = got[("phys.pka.acid.1", 12.57)], got[("phys.pka.base.1", 8.91)]
    assert acid.conditions["acid or base"] == "acid" and base.conditions["acid or base"] == "base"
    assert acid.confidence == base.confidence == "C" and acid.quote == "cx_most_apka: 12.57"
    assert any("1 pKa value(s) without saying acid or base" in n for n in outcome.notes)    # PubChem's "pKa = 9.1": not filed


def test_every_value_is_quoted_from_a_stored_page_with_where_it_came_from(tmp_path):
    ws, _outcome = _read(tmp_path)
    library = DocumentLibrary(ws)
    for item in items(ws):
        page = library.page_text(item.source.doc_sha256, 1)
        assert page and item.quote.replace("  ", " ") in page, item.target
        assert library.entry(item.source.doc_sha256).retrieved is not None          # the source and its address


def test_reading_again_proposes_nothing_twice(tmp_path):
    ws, first = _read(tmp_path)
    again = read_compound_sources(ws, DocumentLibrary(ws), literature_items(derive(empty_brief(answers.DRUG, by="u"))),
                                  drug=answers.DRUG, actor="agent:again", pubchem=answers.clients()[0],
                                  openfda=answers.clients()[1], chembl=answers.clients()[2])
    assert len(first.proposed) == 8 and again.proposed == [] and len(items(ws)) == 8


def test_a_source_that_cannot_be_reached_is_recorded_and_the_others_still_read(tmp_path):
    ws, outcome = _read(tmp_path, unreachable=("api.fda.gov",))
    label = next(s for s in outcome.sources if s["name"] == "FDA label")
    assert not label["ok"] and "not reachable" in label["detail"] and outcome.status == "COMPLETED"
    assert not any(e.target == "bind.fu" for e in items(ws)) and any(e.target == "phys.mw" for e in items(ws))
    _ws, none = _read(tmp_path / "none", unreachable=("api.fda.gov", "pubchem.ncbi.nlm.nih.gov", "www.ebi.ac.uk"))
    assert none.status == "NO_SOURCE" and none.proposed == []


def test_chembl_answers_only_the_molecule_of_that_exact_name():
    _pubchem, _openfda, chembl = answers.clients()
    assert chembl.molecule("EXZ-101").chembl_id == "CHEMBL0000001"              # a synonym ChEMBL lists
    with pytest.raises(SourceError, match="no molecule of exactly this name"):
        chembl.molecule("Exampleamide N")


@pytest.mark.parametrize(("text", "found"), [
    ("Exampleamide is approximately 91% protein bound.", ("Exampleamide is approximately 91% protein bound.", 91.0, "% bound")),
    ("Plasma protein binding of X is about 30%.", ("Plasma protein binding of X is about 30%.", 30.0, "% bound")),
    ("The unbound fraction in plasma protein binding studies was 9%.",
     ("The unbound fraction in plasma protein binding studies was 9%.", 9.0, "%")),
    ("X is highly bound (>99%) to plasma proteins.", None),                  # a bound, not a value
    ("Protein binding ranged from 27% to 30%.", None),                       # a range
    ("The metabolite M1 is 60% bound to plasma proteins.", None),           # the metabolite's, not the drug's
    ("X is extensively bound to plasma proteins.", None),                   # no number
])
def test_the_label_binding_is_taken_only_when_one_number_states_it(text, found):
    assert _binding_sentence(text) == found


def test_an_answer_in_another_shape_is_recorded_as_not_read_and_the_others_still_read(tmp_path):
    """The shapes are those the services document; one that changes stops nothing but its own source."""
    import httpx

    from modeler_agents.structured_sources import OpenFDA

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    pubchem, _openfda, chembl = answers.clients()
    odd = OpenFDA(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [{"pharmacokinetics": 7}]})))
    outcome = read_compound_sources(ws, DocumentLibrary(ws), literature_items(derive(empty_brief(answers.DRUG, by="u"))),
                                    drug=answers.DRUG, actor="agent:t", pubchem=pubchem, openfda=odd, chembl=chembl)
    label = next(s for s in outcome.sources if s["name"] == "FDA label")
    assert not label["ok"] and "could not be read" in label["detail"]
    assert [s["ok"] for s in outcome.sources] == [True, False, True] and len(outcome.proposed) == 7
