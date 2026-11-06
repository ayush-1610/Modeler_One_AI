"""Recorded answers of PubChem, openFDA and ChEMBL for an invented compound, Exampleamide (software test data, never a
real drug's values), in the shapes the services document: PUG REST's property table, PUG-View's Record of sections,
openFDA's `results` of labels, ChEMBL's `molecules`. Tests and the browser flows answer from these instead of the
network; `modeler_agents.structured_sources.capture` saves the live answers to check the shapes.
"""

from __future__ import annotations

import json

import httpx

DRUG = "Exampleamide"
CID = 99000001

PROPERTIES = {"PropertyTable": {"Properties": [{
    "CID": CID, "MolecularFormula": "C20H24ClNO5", "MolecularWeight": "393.9", "XLogP": 2.4,
    "InChIKey": "XXXXXXXXXXXXXX-XXXXXXXXXX-N"}]}}

EXPERIMENTAL = {"Record": {
    "RecordType": "CID", "RecordNumber": CID, "RecordTitle": DRUG,
    "Section": [{"TOCHeading": "Chemical and Physical Properties", "Section": [{
        "TOCHeading": "Experimental Properties", "Section": [
            {"TOCHeading": "LogP", "Information": [
                {"ReferenceNumber": 7, "Reference": ["Invented A, Example B; Test Data Journal 1: 1 (2020)"],
                 "Value": {"StringWithMarkup": [{"String": "log Kow = 2.1"}]}},
                {"ReferenceNumber": 8, "Value": {"StringWithMarkup": [{"String": "log Kow = 2.9 (est)"}]}}]},
            {"TOCHeading": "Solubility", "Information": [
                {"ReferenceNumber": 7, "Value": {"StringWithMarkup": [{"String": "In water, 1.5X10+3 mg/L at 25 °C"}]}},
                {"ReferenceNumber": 9, "Value": {"StringWithMarkup": [{"String": "Freely soluble in ethanol"}]}}]},
            {"TOCHeading": "Dissociation Constants", "Information": [
                {"ReferenceNumber": 7, "Value": {"StringWithMarkup": [{"String": "pKa = 9.1"}]}}]},
            {"TOCHeading": "Melting Point", "Information": [
                {"ReferenceNumber": 9, "Value": {"StringWithMarkup": [{"String": "151 °C"}]}}]}]}]}],
    "Reference": [
        {"ReferenceNumber": 7, "SourceName": "Hazardous Substances Data Bank (HSDB)", "SourceID": "0000"},
        {"ReferenceNumber": 8, "SourceName": "Hazardous Substances Data Bank (HSDB)", "SourceID": "0000"},
        {"ReferenceNumber": 9, "SourceName": "Example Chemical Supplier", "SourceID": "E-1"}]}}

_PK = ("12.3 Pharmacokinetics Absorption Following oral administration of EXAMPLIX, the maximum plasma concentration is "
       "usually attained within 2 hours under fasting state. Distribution Exampleamide is approximately 85% bound to human "
       "plasma proteins. Protein binding is not meaningfully altered in renal or hepatic impairment. Elimination The mean "
       "plasma terminal half-life (t1/2) for exampleamide is approximately 12.9 hours following a single oral dose of 10 mg.")
LABELS = {"meta": {"results": {"skip": 0, "limit": 20, "total": 2}}, "results": [
    {"id": "generic-label", "set_id": "00000000-0000-0000-0000-000000000002", "version": "3", "effective_time": "20250101",
     "pharmacokinetics": [_PK.replace("EXAMPLIX", "exampleamide tablets")],
     "openfda": {"brand_name": ["Exampleamide"], "generic_name": ["EXAMPLEAMIDE"], "application_number": ["ANDA000002"]}},
    {"id": "innovator-label", "set_id": "00000000-0000-0000-0000-000000000001", "version": "12", "effective_time": "20240301",
     "pharmacokinetics": [_PK],
     "openfda": {"brand_name": ["EXAMPLIX"], "generic_name": ["EXAMPLEAMIDE"], "application_number": ["NDA000001"]}}]}

MOLECULES = {"molecules": [
    {"molecule_chembl_id": "CHEMBL0000002", "pref_name": "EXAMPLEAMIDE N-OXIDE", "molecule_synonyms": [],
     "molecule_properties": {"cx_most_apka": "11.02", "cx_most_bpka": None}},
    {"molecule_chembl_id": "CHEMBL0000001", "pref_name": "EXAMPLEAMIDE",
     "molecule_synonyms": [{"molecule_synonym": "EXZ-101", "syn_type": "RESEARCH_CODE"}],
     "molecule_properties": {"cx_most_apka": "12.57", "cx_most_bpka": "8.91", "cx_logp": "2.30", "full_mwt": "393.87"}}],
    "page_meta": {"limit": 10, "offset": 0, "total_count": 2}}


def transport(*, unreachable: tuple[str, ...] = ()) -> httpx.MockTransport:
    """A transport that answers as the services would for Exampleamide (404 for any other name); the hosts named in
    `unreachable` refuse the connection."""

    def answer(request: httpx.Request) -> httpx.Response:
        host, path, query = request.url.host, request.url.path, str(request.url.params)
        if host in unreachable:
            raise httpx.ConnectError("refused", request=request)
        if host == "pubchem.ncbi.nlm.nih.gov":
            if path.startswith(f"/rest/pug/compound/name/{DRUG}/"):
                return httpx.Response(200, text=json.dumps(PROPERTIES, indent=2))
            if path == f"/rest/pug_view/data/compound/{CID}/JSON":
                return httpx.Response(200, json=EXPERIMENTAL)
        if host == "api.fda.gov" and DRUG.lower() in query.lower():
            return httpx.Response(200, json=LABELS)
        if host == "www.ebi.ac.uk" and any(n in query.lower() for n in (DRUG.lower(), "exz-101")):
            return httpx.Response(200, json=MOLECULES)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(answer)


def clients(*, unreachable: tuple[str, ...] = ()):
    """PubChem, openFDA and ChEMBL clients answering from the recorded answers."""
    from modeler_agents.structured_sources import ChEMBL, OpenFDA, PubChem

    t = transport(unreachable=unreachable)
    return PubChem(transport=t), OpenFDA(transport=t), ChEMBL(transport=t)
