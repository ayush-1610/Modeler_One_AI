"""Free structured sources for a compound's values, read by code with no AI (plan 2026-11-05 §3.3; the owner's answer
of 2026-11-05: sources accepted by regulators or peer-reviewed, none that needs a licence).

- **PubChem** (NCBI): the compound's computed properties over PUG REST (molecular weight, formula, XLogP3), and the
  experimental properties PubChem cites (logP, solubility, pKa) over PUG-View, each with the reference PubChem gives.
- **openFDA**: the FDA drug label (structured product labeling), its §12.3 Pharmacokinetics as the label states it.
- **ChEMBL** (EMBL-EBI): the molecule's computed properties (ChemAxon's most acidic and most basic pKa).

Each answer is turned into a text that a value can be quoted from: PubChem's property table and ChEMBL's properties
as the JSON lines they answer, PUG-View's sections one line per item with its reference, the label's section as
written. Nothing here decides a value; `compound_sources` proposes, and the grade and source selection rank them.

The response shapes are those the services document (PUG REST, PUG-View, openFDA `drug/label`, the ChEMBL web services).
The tests run on recorded answers in those shapes (software test data with an invented compound); `capture` fetches
the live answers on a host that reaches the services, to check the shapes. The HTTP transport is injectable, as for
Europe PMC (`modeler_agents.sources`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from modeler_agents.sources import SourceError

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest"
OPENFDA = "https://api.fda.gov/drug/label.json"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
PUBCHEM_PROPERTIES = "MolecularFormula,MolecularWeight,XLogP,InChIKey"
EXPERIMENTAL = ("LogP", "Solubility", "Dissociation Constants")


def _get(name: str, url: str, *, transport: httpx.BaseTransport | None, timeout_s: float,
         params: dict[str, Any] | None = None) -> httpx.Response:
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as client:
            response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise SourceError(f"{name} is not reachable from this host ({type(exc).__name__})") from exc
    if response.status_code == 404:
        raise SourceError(f"{name} has no entry for this name")
    if response.status_code != 200:
        raise SourceError(f"{name} answered HTTP {response.status_code}")
    return response


def _json(name: str, response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise SourceError(f"{name}'s answer is not JSON") from exc


# --- PubChem --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PubChemProperties:
    cid: int
    url: str
    text: str                       # the answer as PubChem gave it (the values are quoted from it)
    properties: dict[str, Any]


@dataclass(frozen=True)
class ExperimentalItem:
    heading: str                    # LogP, Solubility, Dissociation Constants
    value: str                      # the item as PubChem writes it ("log Kow = 2.6"; a number with its unit)
    reference: str                  # the source PubChem cites for it


@dataclass(frozen=True)
class PubChemExperimental:
    cid: int
    url: str
    items: list[ExperimentalItem] = field(default_factory=list)

    def text(self, drug: str) -> str:
        """The page a value is quoted from: one line per item, with the reference PubChem cites."""
        lines = [f"PubChem compound {self.cid} ({drug}): Experimental Properties, as PubChem lists them",
                 f"Source: {self.url}", ""]
        lines += [f"{i.heading}: {i.value} [{i.reference}]" if i.reference else f"{i.heading}: {i.value}" for i in self.items]
        return "\n".join(lines) + "\n"


class PubChem:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout_s: float = 20.0):
        self._transport, self._timeout = transport, timeout_s

    def properties(self, name: str) -> PubChemProperties:
        url = f"{PUBCHEM}/pug/compound/name/{quote(name.strip())}/property/{PUBCHEM_PROPERTIES}/JSON"
        response = _get("PubChem", url, transport=self._transport, timeout_s=self._timeout)
        try:
            props = _json("PubChem", response)["PropertyTable"]["Properties"][0]
            cid = int(props["CID"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SourceError("PubChem's answer has no property table") from exc
        return PubChemProperties(cid=cid, url=url, text=response.text, properties=dict(props))

    def experimental(self, cid: int) -> PubChemExperimental:
        """The Experimental Properties PubChem cites for the compound (LogP, Solubility, Dissociation Constants)."""
        url = f"{PUBCHEM}/pug_view/data/compound/{cid}/JSON"
        response = _get("PubChem", url, transport=self._transport, timeout_s=self._timeout,
                        params={"heading": "Experimental Properties"})
        record = (_json("PubChem", response) or {}).get("Record") or {}
        references = {r.get("ReferenceNumber"): r for r in record.get("Reference", []) if isinstance(r, dict)}
        items: list[ExperimentalItem] = []

        def walk(sections: list[dict[str, Any]]) -> None:
            for section in sections:
                heading = section.get("TOCHeading", "")
                if heading in EXPERIMENTAL:
                    for info in section.get("Information", []):
                        value = _value_text(info.get("Value") or {})
                        if value:
                            items.append(ExperimentalItem(heading, value, _reference(info, references)))
                walk(section.get("Section", []))

        walk(record.get("Section", []))
        return PubChemExperimental(cid=cid, url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}", items=items)


def _value_text(value: dict[str, Any]) -> str:
    strings = [s.get("String", "") for s in value.get("StringWithMarkup", []) if isinstance(s, dict)]
    if any(strings):
        return " ".join(" ".join(s.split()) for s in strings if s)
    numbers = value.get("Number")
    if isinstance(numbers, list) and numbers:
        return " ".join(f"{n:g}" for n in numbers if isinstance(n, int | float)) + (f" {value['Unit']}" if value.get("Unit") else "")
    return ""


def _reference(info: dict[str, Any], references: dict[Any, dict[str, Any]]) -> str:
    """What PubChem cites for an item: the item's own reference text, else its source's name."""
    own = info.get("Reference")
    if isinstance(own, list) and own:
        return " ".join(str(own[0]).split())
    source = references.get(info.get("ReferenceNumber")) or {}
    return " ".join(str(source.get("SourceName") or source.get("Name") or "").split())


# --- openFDA --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Label:
    brand: str
    generic: str
    application: str                 # NDA… for the innovator, ANDA… for a generic
    effective: str                   # YYYYMMDD
    set_id: str
    section: str                     # "12.3 Pharmacokinetics" or the clinical pharmacology section when that is all
    text: str                        # the section as the label states it

    @property
    def url(self) -> str:
        return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={self.set_id}"

    def page(self) -> str:
        """The page a value is quoted from: who issued the label and when, then the section as written."""
        head = f"FDA label: {self.brand} ({self.generic}), {self.application}, effective {self.effective}"
        return f"{head}\nSource: openFDA drug label, {self.url}\n\n{self.text}\n"


class OpenFDA:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout_s: float = 20.0):
        self._transport, self._timeout = transport, timeout_s

    def label(self, generic_name: str) -> Label:
        """The label to read: the innovator's (an NDA) before a generic's, the most recent first."""
        response = _get("openFDA", OPENFDA, transport=self._transport, timeout_s=self._timeout,
                        params={"search": f'openfda.generic_name:"{generic_name.strip()}"', "limit": 20})
        results = [r for r in (_json("openFDA", response) or {}).get("results", []) if isinstance(r, dict)]
        usable = [r for r in results if r.get("pharmacokinetics") or r.get("clinical_pharmacology")]
        if not usable:
            raise SourceError("openFDA has no label with a pharmacokinetics section for this name")

        def first(r: dict[str, Any], key: str) -> str:
            values = (r.get("openfda") or {}).get(key) or [""]
            return str(values[0])

        def rank(r: dict[str, Any]) -> tuple[bool, str]:
            return first(r, "application_number").upper().startswith("NDA"), str(r.get("effective_time", ""))

        best = max(usable, key=rank)
        section, text = (("12.3 Pharmacokinetics", best["pharmacokinetics"]) if best.get("pharmacokinetics")
                         else ("12 Clinical pharmacology", best["clinical_pharmacology"]))
        return Label(brand=first(best, "brand_name"), generic=first(best, "generic_name"),
                     application=first(best, "application_number"), effective=str(best.get("effective_time", "")),
                     set_id=str(best.get("set_id", "")), section=section,
                     text="\n\n".join(" ".join(str(t).split()) for t in text))


# --- ChEMBL ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChEMBLMolecule:
    chembl_id: str
    name: str
    properties: dict[str, Any]

    @property
    def url(self) -> str:
        return f"https://www.ebi.ac.uk/chembl/compound_report_card/{self.chembl_id}/"

    def page(self) -> str:
        """The page a value is quoted from: the molecule's computed properties as ChEMBL answers them."""
        lines = [f"ChEMBL {self.chembl_id} ({self.name}): molecule_properties, computed by ChEMBL", f"Source: {self.url}", ""]
        lines += [f"{k}: {v}" for k, v in sorted(self.properties.items()) if v not in (None, "")]
        return "\n".join(lines) + "\n"


class ChEMBL:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout_s: float = 20.0):
        self._transport, self._timeout = transport, timeout_s

    def molecule(self, name: str) -> ChEMBLMolecule:
        """The molecule ChEMBL names so (its preferred name or a synonym); never the nearest match."""
        response = _get("ChEMBL", f"{CHEMBL}/molecule/search.json", transport=self._transport, timeout_s=self._timeout,
                        params={"q": name.strip(), "limit": 10})
        wanted = name.strip().lower()
        for molecule in (_json("ChEMBL", response) or {}).get("molecules", []):
            names = {str(molecule.get("pref_name") or "").lower()}
            names |= {str(s.get("molecule_synonym") or "").lower() for s in molecule.get("molecule_synonyms") or []
                      if isinstance(s, dict)}
            if wanted in names:
                return ChEMBLMolecule(chembl_id=str(molecule.get("molecule_chembl_id", "")),
                                      name=str(molecule.get("pref_name") or name),
                                      properties=dict(molecule.get("molecule_properties") or {}))
        raise SourceError("ChEMBL has no molecule of exactly this name")


def capture(drug: str, folder: str) -> list[str]:
    """Save the live answers for one drug (to check the shapes this module reads, on a host that reaches the services)."""
    from pathlib import Path

    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    calls = [("pubchem-properties.json", f"{PUBCHEM}/pug/compound/name/{quote(drug)}/property/{PUBCHEM_PROPERTIES}/JSON", None),
             ("openfda-label.json", OPENFDA, {"search": f'openfda.generic_name:"{drug}"', "limit": 20}),
             ("chembl-search.json", f"{CHEMBL}/molecule/search.json", {"q": drug, "limit": 10})]
    for name, url, params in calls:
        response = _get(name, url, transport=None, timeout_s=30.0, params=params)
        (out / name).write_text(response.text, encoding="utf-8")
        saved.append(name)
        if name == "pubchem-properties.json":
            cid = int(response.json()["PropertyTable"]["Properties"][0]["CID"])
            view = _get("PubChem", f"{PUBCHEM}/pug_view/data/compound/{cid}/JSON", transport=None, timeout_s=30.0,
                        params={"heading": "Experimental Properties"})
            (out / "pubchem-experimental.json").write_text(view.text, encoding="utf-8")
            saved.append("pubchem-experimental.json")
    return saved


if __name__ == "__main__":   # python -m modeler_agents.structured_sources <drug> <folder>
    import sys

    print("\n".join(capture(sys.argv[1], sys.argv[2])))
