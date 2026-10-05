"""T-41: the Project Brief, its locking rule, identity resolution and the document library."""

from __future__ import annotations

import json

import httpx
import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import (
    Citation,
    FieldStatus,
    ProjectBrief,
    coerce,
    definition_of,
    empty_brief,
    parse_path,
    set_record,
    validate_brief,
)
from modeler_project.brief_ops import EditError, agent_set, check_structure, edit_field, locked, resolve_identity
from modeler_project.documents import DocumentLibrary
from modeler_project.identity import IdentityError, fetch_pubchem, from_smiles

pytestmark = pytest.mark.req("T-41")

DAPA_SMILES = "CCOC1=CC=C(C=C1)CC2=C(C=CC(=C2)[C@H]3[C@@H]([C@H]([C@@H]([C@H](O3)CO)O)O)O)Cl"
SHA = "a" * 64


def _cite(quote="single oral dose of 50 mg"):
    return (Citation(doc_sha256=SHA, page=1, quote=quote),)


def test_paths_and_coercion():
    assert parse_path("drug.salt_form") == (None, 0, "drug.salt_form")
    assert parse_path("products[2].role") == ("products", 2, "role")
    with pytest.raises(ValueError):
        parse_path("products[0].colour")
    assert coerce(definition_of("scenarios[0].dose"), "50 mg") == 50.0
    assert coerce(definition_of("products[0].role"), "rld") == "RLD"
    assert coerce(definition_of("qoi.applications"), ["APP-12"]) == ["APP-12 food effect"]
    with pytest.raises(ValueError, match="not one of"):
        coerce(definition_of("drug.modality"), "peptide-ish")


def test_empty_brief_needs_the_required_fields_before_approval():
    brief = empty_brief("Dapagliflozin", by="u1")
    assert brief.get("drug.name").status is FieldStatus.ENTERED
    codes = {(i.code, i.path) for i in validate_brief(brief)}
    assert ("REQUIRED_MISSING", "qoi.text") in codes and ("REQUIRED_MISSING", "products") in codes
    assert ("REQUIRED_MISSING", "drug.name") not in codes


def test_people_lock_fields_and_agents_cannot_overwrite_them():
    brief = empty_brief("X", by="u1")
    brief = agent_set(brief, "scenarios[0].dose", value="50", unit="mg", citations=_cite(), status=FieldStatus.EXTRACTED,
                      confidence="A", by="agent:a1")
    brief = edit_field(brief, "scenarios[0].dose", value=100, status=FieldStatus.EDITED, note="amendment 2 raised the dose",
                       by="u1")
    assert locked(brief, "scenarios[0].dose") and brief.value("scenarios[0].dose") == 100.0
    with pytest.raises(EditError, match="does not overwrite|do not overwrite"):
        agent_set(brief, "scenarios[0].dose", value="50", unit="mg", citations=_cite(), status=FieldStatus.EXTRACTED,
                  confidence="A", by="agent:a1")
    with pytest.raises(EditError, match="person only"):
        agent_set(brief, "acceptance.tier", value="high", unit=None, citations=_cite(), status=FieldStatus.EXTRACTED,
                  confidence="A", by="agent:a1")
    with pytest.raises(EditError, match="say why"):
        edit_field(brief, "drug.cas", value="461432-26-8", status=FieldStatus.EDITED, note="", by="u1")


def test_group_items_append_in_order():
    brief = empty_brief("X", by="u1")
    brief = agent_set(brief, "products[0].name", value="Forxiga 10 mg", unit=None, citations=_cite(),
                      status=FieldStatus.EXTRACTED, confidence="A", by="a")
    with pytest.raises(ValueError, match="first"):
        set_record(brief, "products[2].name", brief.get("products[0].name"))
    assert len(brief.groups["products"]) == 1


def test_structure_check_computes_mw_and_flags_a_disagreeing_stated_mw():
    identity = from_smiles(DAPA_SMILES)
    assert identity.formula == "C21H25ClO6" and identity.halogens["Cl"] == 1 and abs(identity.mw - 408.88) < 0.01
    brief = edit_field(empty_brief("Dapagliflozin", by="u"), "drug.smiles", value=DAPA_SMILES,
                       status=FieldStatus.EDITED, note="from the label", by="u")
    computed, _ = check_structure(brief, by="system")
    assert computed.get("drug.mw_free_base").status is FieldStatus.COMPUTED
    wrong = edit_field(brief, "drug.mw_free_base", value=502.9, status=FieldStatus.EDITED, note="proposal table 1", by="u")
    flagged, notes = check_structure(wrong, by="system")
    assert flagged.questions and "salt form" in notes[0]


def test_pubchem_answer_is_stored_and_quoted_verbatim(tmp_path):
    body = json.dumps({"PropertyTable": {"Properties": [{"CID": 9887712, "MolecularFormula": "C21H25ClO6",
                                                         "MolecularWeight": "408.9", "IsomericSMILES": DAPA_SMILES,
                                                         "InChIKey": "JVHXJTBJCFBINQ-ADAARDCZSA-N",
                                                         "IUPACName": "x"}]}})
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    library = DocumentLibrary(ws)

    def store(record):
        return library.add_text(record.text, "pubchem-dapagliflozin.txt", role="retrieved_record", by="system").content["sha256"]

    brief, _notes = resolve_identity(empty_brief("Dapagliflozin", by="u"), store_record=store, by="system",
                                    fetch=lambda name: fetch_pubchem(name, transport=transport))
    smiles = brief.get("drug.smiles")
    assert smiles.status is FieldStatus.RETRIEVED and smiles.value == DAPA_SMILES
    page = library.page_text(smiles.citations[0].doc_sha256, 1)
    assert smiles.citations[0].quote in page and '"CID": 9887712' in brief.get("drug.pubchem_cid").citations[0].quote
    assert brief.get("drug.mw_free_base").status is FieldStatus.COMPUTED


def test_pubchem_unreachable_is_a_note_not_a_failure():
    def boom(name):
        raise IdentityError("PubChem is not reachable from this host")

    brief, notes = resolve_identity(empty_brief("X", by="u"), store_record=lambda r: SHA, by="s", fetch=boom)
    assert "not reachable" in notes[0] and brief.get("drug.smiles").status is FieldStatus.MISSING


def test_library_stores_documents_once_and_searches_pages(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    library = DocumentLibrary(ws)
    first = library.add(b"Objective\fThe client provides dissolution data in three media.", "proposal.txt",
                        role="proposal", by="u")
    again = library.add(b"Objective\fThe client provides dissolution data in three media.", "copy.txt", role="proposal", by="u")
    assert first == again and first.kind is ArtifactKind.DOCUMENT and first.content["n_pages"] == 2
    hits = library.search("dissolution media")
    assert hits[0].page == 2 and "three media" in hits[0].snippet
    assert library.page_text(first.content["sha256"], 2).startswith("The client")
    assert ProjectBrief.from_content(empty_brief("X", by="u").to_content()).drug_name == "X"
