"""CPF parameter -> PK-Sim simulation parameter path, for parameter identification (fit-apply loop).

The parameter identification spec fits a parameter by its path inside the loaded simulation (run_pi.R:
``getParameter(path=..., container=simulation)``), so the fit step must know where each CPF parameter lives
in the built PK-Sim model. These paths were HARVESTED from a real exported simulation on the Linux engine
(``getAllParameterPathsIn`` on example_snapshot-IV.pkml, ospsuite 12.4.4, adt-server, 2026-09-18); they are
never guessed. The container patterns are standard PK-Sim structure, but a real per-compound path can still
vary, so the fit-spec builder MUST verify each resolved path exists in the actual simulation before fitting.

Harvested facts (compound "Example-A", molecule "CYP3A4", data source "Example"):
- compound physicochemistry:  ``{compound}|<name>``            e.g. ``Example-A|Lipophilicity``
- molecule-based process:     ``{compound}-{molecule}-{data_source}|<name>``  e.g. ``Example-A-CYP3A4-Example|CLspec/[Enzyme]``
- glomerular filtration:      ``Neighborhoods|Kidney_pls_Kidney_ur|{compound}|Glomerular Filtration-{data_source}-{compound}|GFR fraction``
"""

from __future__ import annotations

from pbpk_domain.cpf.models import ParameterRecord

# Compound-level physicochemistry, keyed by CPF parameter id -> the PK-Sim compound parameter name (harvested).
_COMPOUND_PARAM: dict[str, str] = {
    "phys.mw": "Molecular weight",
    "phys.logp": "Lipophilicity",
    "bind.fu": "Fraction unbound (plasma, reference value)",
    "phys.solubility.ref": "Solubility at reference pH",
    "perm.intestinal": "Specific intestinal permeability (transcellular)",
    "perm.cellular": "Permeability",
}

# Process internal names whose kinetic input parameters live in the `{compound}-{molecule}-{data_source}`
# reaction container (harvested for metabolization; the other molecule-based processes share the structure).
_MOLECULE_PROCESSES = frozenset({
    "MetabolizationSpecific_FirstOrder", "MetabolizationSpecific_MM", "MetabolizationLiverMicrosomes_MM",
    "rCYP450_MM", "ActiveTransportSpecific_MM", "CompetitiveInhibition", "Induction", "SpecificBinding",
})
_GFR_PROCESS = "GlomerularFiltration"


class ParameterPathError(ValueError):
    """A CPF parameter cannot be mapped to a PK-Sim path from the harvested set (never invented)."""


def pksim_parameter_path(record: ParameterRecord, *, compound: str) -> str:
    """The PK-Sim simulation parameter path a fit targets for this CPF record.

    Raises ParameterPathError when the parameter has no harvested path (so the fit step surfaces the gap
    instead of fitting an invented path)."""
    binding = record.engine_binding
    internal = binding.process_internal_name if binding else None

    # Compound-level physicochemistry (no process): keyed by CPF id, falling back to the binding's own name.
    if internal is None:
        name = _COMPOUND_PARAM.get(record.id)
        if name is None and binding is not None and binding.building_block == "Compound":
            name = binding.parameter
        if name is None:
            raise ParameterPathError(f"no harvested compound path for CPF parameter {record.id!r}")
        return f"{compound}|{name}"

    data_source = binding.data_source
    if not data_source:
        raise ParameterPathError(f"{record.id!r}: process {internal} needs a data source to locate its path")
    param = binding.parameter

    if internal == _GFR_PROCESS:
        return f"Neighborhoods|Kidney_pls_Kidney_ur|{compound}|Glomerular Filtration-{data_source}-{compound}|{param}"

    if internal in _MOLECULE_PROCESSES:
        molecule = binding.molecule
        if not molecule:
            raise ParameterPathError(f"{record.id!r}: molecule-based process {internal} needs a molecule")
        return f"{compound}-{molecule}-{data_source}|{param}"

    raise ParameterPathError(f"{record.id!r}: no harvested path for process {internal!r}")
