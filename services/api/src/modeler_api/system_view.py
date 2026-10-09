"""The project's model system as the system panel shows it (MS-01 v1.3 §6.5): every compound and its role, the
formation links, the products with their dose fractions, and each analyte with the compounds it informs and the
stages that judge it. Read from the stored links and each compound's current CPF."""

from __future__ import annotations

from typing import Any

from pbpk_domain.cpf import CPF

_STAGES = ("S1", "S2", "S3", "SM", "SJ", "S4", "S5")


def system_detail(links_doc: dict[str, Any], cpfs: dict[str, CPF]) -> dict[str, Any]:
    from pbpk_domain.system import SystemLinks, analyte_molecular_weight, assemble, gated, subjects

    links = SystemLinks.model_validate(links_doc)
    fitted = next((c for c in links.compounds if links.roles.get(c) == "parent"), links.compounds[0])
    detail: dict[str, Any] = {
        "name": links.name, "fitted": fitted,
        "compounds": [{"compound": c, "role": links.roles[c], "has_cpf": c in cpfs} for c in links.compounds],
        "formation": [{"compound": f.compound, "metabolite": f.metabolite, "process": f"{f.internal_name}:{f.molecule}",
                       "data_source": f.data_source} for f in links.formation],
        "products": links.products, "analytes": [], "sha256": None, "problem": "",
    }
    try:
        system = assemble(links, cpfs)
    except ValueError as exc:  # a compound without its CPF yet: the links are shown, the gating once all are there
        detail["problem"] = str(exc)
        detail["analytes"] = [{"name": a.name, "kind": a.kind, "informs": [], "judged_at": [], "note": ""}
                              for a in links.analytes.values()]
        return detail
    rows = []
    for a in system.analytes.values():
        informs = list(subjects(system, a.name, fitted))
        _weight, why = analyte_molecular_weight(system, a.name)
        metabolites = bool(informs) and all(system.roles[c] == "metabolite" for c in informs)
        rows.append({"name": a.name, "kind": a.kind, "informs": informs,
                     # SM plans only metabolite studies; a parent's are judged at the parent stages
                     "judged_at": [s for s in _STAGES if gated(system, a.name, fitted, s) and (s != "SM" or metabolites)],
                     "note": why or ("" if informs else "a sum of a parent and a metabolite: reported, never judged")})
    detail["analytes"], detail["sha256"] = rows, system.sha256
    return detail
