"""Drug identity for the brief and the CPF: structure-derived values (RDKit) and the PubChem record (plan §6 B).

MS-01 §2.2 cross-checks identity with RDKit: the molecular weight computed from the structure against the stated one,
and the halogen counts PK-Sim needs for its effective molecular weight (`phys.halogens.*`). PubChem is reached over
its public PUG REST API; the answer is stored as a retrieved-record document so every value taken from it is quoted
from exactly what PubChem returned. The HTTP call is injectable (a test transport, or None when the host has no
outbound access: the build container blocks PubChem; the server must allow it, decision D-17).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

import httpx

PUBCHEM_PROPERTIES = "MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,InChIKey,IUPACName"
PUBCHEM_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/{props}/JSON"
HALOGENS = {"F": 9, "Cl": 17, "Br": 35, "I": 53}


@dataclass(frozen=True)
class StructureIdentity:
    smiles: str
    formula: str
    mw: float
    inchikey: str
    halogens: dict[str, int]


class IdentityError(ValueError):
    pass


def from_smiles(smiles: str) -> StructureIdentity:
    """Formula, average molecular weight, InChIKey and halogen counts from a SMILES string (RDKit)."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors, rdMolDescriptors

    RDLogger.DisableLog("rdApp.*")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise IdentityError(f"not a valid SMILES: {smiles!r}")
    counts = {symbol: 0 for symbol in HALOGENS}
    for atom in mol.GetAtoms():
        if atom.GetSymbol() in counts:
            counts[atom.GetSymbol()] += 1
    return StructureIdentity(smiles=smiles, formula=rdMolDescriptors.CalcMolFormula(mol), mw=round(Descriptors.MolWt(mol), 4),
                             inchikey=Chem.MolToInchiKey(mol), halogens=counts)


def mw_agrees(stated: float, computed: float, *, rel_tol: float = 0.002) -> bool:
    """Stated and structure-derived molecular weights agree within 0.2 % (rounding in papers, not a salt form)."""
    return abs(stated - computed) <= rel_tol * computed


@dataclass(frozen=True)
class PubChemRecord:
    query: str
    text: str            # the response body exactly as returned (stored as the retrieved-record document)
    cid: int
    formula: str
    mw: float
    smiles: str
    inchikey: str
    iupac_name: str


def fetch_pubchem(name: str, *, transport: httpx.BaseTransport | None = None, timeout_s: float = 30.0) -> PubChemRecord:
    url = PUBCHEM_URL.format(name=quote(name.strip()), props=PUBCHEM_PROPERTIES)
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise IdentityError(f"PubChem is not reachable from this host ({type(exc).__name__}); enter the structure by hand "
                            "or allow outbound access to pubchem.ncbi.nlm.nih.gov") from exc
    if response.status_code == 404:
        raise IdentityError(f"PubChem has no compound named {name!r}")
    if response.status_code != 200:
        raise IdentityError(f"PubChem answered HTTP {response.status_code}")
    text = response.text
    try:
        props = json.loads(text)["PropertyTable"]["Properties"][0]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise IdentityError("PubChem's answer did not contain a property table") from exc
    smiles = props.get("IsomericSMILES") or props.get("CanonicalSMILES") or props.get("SMILES") or ""
    return PubChemRecord(query=name, text=text, cid=int(props["CID"]), formula=str(props.get("MolecularFormula", "")),
                         mw=float(props.get("MolecularWeight", 0) or 0), smiles=str(smiles), inchikey=str(props.get("InChIKey", "")),
                         iupac_name=str(props.get("IUPACName", "")))
