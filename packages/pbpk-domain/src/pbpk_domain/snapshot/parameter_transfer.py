"""Write identified parameter values back into a snapshot, the way PK-Sim's "Transfer to Simulation" does.

PK-Sim stores a transferred value as a simulation-level parameter override with a ``ValueOrigin`` of source
and method ``ParameterIdentification`` and a description naming the run and time, e.g.
``Value updated from 'PI full  (perm)' on 2019-08-23 15:34`` (observed in the OSP Dapagliflozin snapshot).
PI results name parameters with the simulation as first path segment (``IV|Compound|Lipophilicity``); the
snapshot override path omits it (``Compound|Lipophilicity``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pbpk_domain.snapshot.models import Parameter, Snapshot, ValueOrigin


@dataclass(frozen=True)
class IdentifiedValue:
    simulation_path: str  # "<simulation name>|<path inside the simulation>"
    value: float
    unit: str | None = None


def apply_identified_values(snapshot: Snapshot, values: Sequence[IdentifiedValue], *, run_label: str, when: datetime) -> Snapshot:
    """Return a new snapshot with the values applied; the input snapshot is not modified."""
    updated = snapshot.model_copy(deep=True)
    simulations = {s.name: s for s in updated.simulations}
    origin = ValueOrigin(
        source="ParameterIdentification",
        method="ParameterIdentification",
        description=f"Value updated from '{run_label}' on {when:%Y-%m-%d %H:%M}",
    )

    for item in values:
        simulation_name, _, path = item.simulation_path.partition("|")
        if not path:
            raise ValueError(f"{item.simulation_path!r} does not start with a simulation name")
        simulation = simulations.get(simulation_name)
        if simulation is None:
            raise ValueError(f"no simulation named {simulation_name!r} in the snapshot")

        fields: dict = {"path": path, "value": item.value, "value_origin": origin}
        if item.unit is not None:
            fields["unit"] = item.unit
        override = Parameter(**fields)
        parameters = [p for p in simulation.parameters if p.path != path]
        simulation.parameters = [*parameters, override]  # attribute assignment marks the field as set for export
    return updated
