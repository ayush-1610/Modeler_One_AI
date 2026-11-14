"""The mapping cache: approved table mappings by layout, with versions and sign-off (contracts §5, §6.2; plan §7.4).

One hash-chained log, `intake/mappings.jsonl` (`IntakeStore.mappings`), two kinds of line:
- `entry` (`MappingEntry`): a spec stored under the layout fingerprint it was made for (`mapping.fingerprint`), as a
  version of the mapping `"mp-" + fingerprint[:12]`. A rule's or the LLM's spec is proposed and executed at once
  (evidence level `new_mapping`); the same spec as a stored version, WHICHEVER version that is, is that version
  again and nothing is appended (two tables of one layout that need two specs take turns on every run: neither turn
  makes a version); a spec only a rejected version holds comes back as that rejected version, never as a fresh
  proposal (a rejection is not undone by the rules proposing the same spec once more).
- `decision` (`MappingDecision`): a person approves or rejects one version. The latest decision of a version is its
  status (the ledger's fold reads the same lines: `ledger_view`), and a person's approval raises the values read under
  it to `approved_mapping`. One audit event per decision (`intake.mapping.approve` / `.reject`) carries the hash of
  the spec and of the line, so the tenant's audit chain pins this log.

A spec is stored with every `Constant.text` set to None: the model's reading of a name or choice is compared with
code's at proposal and then dropped; on each use the value is what code reads at the cite (`validate_spec` re-reads
every constant and unit from the new region, and a spec that does not read there is a different layout).

`candidates` lists the versions the pipeline may try on a region of the layout: the approved ones, newest first, then
the proposed ones, newest first, never a rejected one. The pipeline validates each on the region's own grid
(`validate_spec`) and uses the first that passes (§6.2 mapping order), so an approved version is not shadowed by a
later version of the same layout that reads another table. `lookup` answers with the first candidate (the latest
approved version, else the latest version not rejected), as before.

For W (§6.2 mapping order): try `candidates(fingerprint)` in their order and use the first whose spec has no error
on the region's own grid; only when none passes go on to the rules (then the LLM). `propose` returns a
`MappingEntry`, which carries no status, and may return a version a person rejected (the rules made the same spec
again). Check `status(mapping_id, version)` after `propose`: a "rejected" version is never executed; the region goes
on to the LLM (or is `unread`, "a person rejected the rule's mapping of this layout"). Reported to the integrator:
`propose` could answer (entry, status) instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from modeler_intake.anchors import check_id, sha256_of
from modeler_intake.mapping_spec import MappingSpec
from modeler_project.intake_records import MappingDecision, MappingEntry
from modeler_project.intake_store import ChainEntry, IntakeStore
from modeler_project.workspace import Workspace

Origin = Literal["rule", "llm", "person"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stored_spec(spec: MappingSpec) -> MappingSpec:
    """The spec as the cache stores it: every `Constant.text` set to None (the value is always code's reading)."""
    return spec.model_copy(update={"constants": tuple(c.model_copy(update={"text": None}) for c in spec.constants)})


def mapping_id_of(fingerprint: str) -> str:
    """The mapping id of a layout fingerprint (a sha256 hex): "mp-" + its first 12 characters."""
    return check_id("mapping", "mp-" + check_id("sha256", fingerprint)[:12])


class MappingCache:
    """The project's mapping cache (see the module docstring). Every read folds the log once; nothing is kept between
    calls, so a cache made per request always reads the current file."""

    def __init__(self, ws: Workspace):
        self.store = IntakeStore(ws)

    # --- reading ---------------------------------------------------------------------------------------------------

    def _fold(self) -> tuple[list[MappingEntry], dict[tuple[str, int], MappingDecision]]:
        entries: list[MappingEntry] = []
        decisions: dict[tuple[str, int], MappingDecision] = {}
        for line in self.store.mappings.entries():
            if line.kind == "entry":
                entries.append(MappingEntry.model_validate(line.body))
            elif line.kind == "decision":
                decision = MappingDecision.model_validate(line.body)
                decisions[(decision.mapping_id, decision.version)] = decision        # the latest decision stands
        return entries, decisions

    def entries(self) -> list[MappingEntry]:
        """Every stored version, in the order they were proposed."""
        return self._fold()[0]

    def get(self, mapping_id: str, version: int | None = None) -> MappingEntry | None:
        """One version of a mapping (None: its latest); None when there is none."""
        check_id("mapping", mapping_id)
        found = [e for e in self.entries() if e.mapping_id == mapping_id and (version is None or e.version == version)]
        return max(found, key=lambda e: e.version) if found else None

    def status(self, mapping_id: str, version: int) -> Literal["approved", "rejected", "proposed"] | None:
        """A version's status: its latest decision, "proposed" with none; None when the version does not exist."""
        entries, decisions = self._fold()
        if not any(e.mapping_id == mapping_id and e.version == version for e in entries):
            return None
        decision = decisions.get((mapping_id, version))
        return decision.status if decision is not None else "proposed"

    def approved(self) -> set[tuple[str, int]]:
        """The (mapping id, version) pairs whose latest decision is an approval."""
        return {key for key, decision in self._fold()[1].items() if decision.status == "approved"}

    def candidates(self, fingerprint: str) -> list[tuple[MappingEntry, str]]:
        """The versions to try on a region of this layout, each with its status: the approved versions, newest first,
        then the proposed ones, newest first; never a rejected one. The caller validates each on the region's own grid
        and uses the first that passes: one layout may hold several versions that each read another table."""
        mapping_id = mapping_id_of(fingerprint)
        entries, decisions = self._fold()
        versions = sorted((e for e in entries if e.mapping_id == mapping_id and e.fingerprint == fingerprint),
                          key=lambda e: e.version, reverse=True)

        def status(entry: MappingEntry) -> str:
            decision = decisions.get((entry.mapping_id, entry.version))
            return decision.status if decision is not None else "proposed"

        return [(e, wanted) for wanted in ("approved", "proposed") for e in versions if status(e) == wanted]

    def lookup(self, fingerprint: str) -> tuple[MappingEntry, str] | None:
        """The spec to try on a region of this layout: (the latest approved version, "approved"), else (the latest
        version not rejected, "proposed"); None when the layout has no usable version. The first of `candidates`."""
        found = self.candidates(fingerprint)
        return found[0] if found else None

    # --- writing ---------------------------------------------------------------------------------------------------

    def propose(self, fingerprint: str, spec: MappingSpec, *, origin: Origin, origin_detail: str,
                first_seen: tuple[str, str], by: str) -> MappingEntry:
        """Store `spec` (its constants' text dropped) as the next version of the layout's mapping and return it. The same
        spec as a stored version, whichever version that is, returns that version and appends nothing (decided under
        the log's lock, so two threads proposing one spec store it once). When several versions hold the spec: the
        newest approved one, else the newest proposed one, else the newest rejected one (the order of `candidates`).
        The answer may therefore be a version a person rejected: the caller checks `status` and never executes a
        rejected version. `first_seen` is (file sha256, region id)."""
        mapping_id = mapping_id_of(fingerprint)
        check_id("sha256", first_seen[0])
        check_id("region", first_seen[1])
        kept = stored_spec(MappingSpec.model_validate(spec.model_dump(by_alias=True)))
        digest = sha256_of(kept)
        found: list[MappingEntry] = []

        def decide(lines: list[ChainEntry]) -> list[tuple[str, dict[str, Any]]]:
            versions = [MappingEntry.model_validate(line.body) for line in lines
                        if line.kind == "entry" and line.body.get("mapping_id") == mapping_id]
            if any(v.fingerprint != fingerprint for v in versions):
                raise ValueError(f"{mapping_id} already holds another layout's mapping (a fingerprint prefix collision)")
            latest = max(versions, key=lambda v: v.version, default=None)
            same = [v for v in versions if sha256_of(v.spec) == digest]
            if same:
                status: dict[int, str] = {}
                for line in lines:
                    if line.kind == "decision" and line.body.get("mapping_id") == mapping_id:
                        status[int(line.body["version"])] = str(line.body["status"])    # the latest decision stands
                rank = {"approved": 2, "proposed": 1, "rejected": 0}
                found.append(max(same, key=lambda v: (rank[status.get(v.version, "proposed")], v.version)))
                return []
            entry = MappingEntry(mapping_id=mapping_id, version=(latest.version + 1) if latest else 1,
                                 fingerprint=fingerprint, spec=kept, origin=origin, origin_detail=origin_detail,
                                 first_seen=first_seen, by=by, at=_now())
            found.append(entry)
            return [("entry", entry.model_dump(mode="json", by_alias=True))]

        self.store.mappings.append_if(decide)
        return found[0]

    def approve(self, mapping_id: str, version: int, *, by: str, note: str = "") -> MappingDecision:
        """A person's approval of one version (audit `intake.mapping.approve`, the note as its reason). Approving a version
        whose latest decision is already an approval appends nothing and returns that decision."""
        return self._decide(mapping_id, version, "approved", by=by, why=note)

    def reject(self, mapping_id: str, version: int, *, by: str, why: str) -> MappingDecision:
        """A person's rejection of one version, with why (audit `intake.mapping.reject`). `candidates` and `lookup` no
        longer answer with it; when the rules make the same spec again, `propose` returns this version and the caller,
        checking `status`, goes on to the LLM. The values read under it keep the level `new_mapping`."""
        if not why.strip():
            raise ValueError("a rejection says why")
        return self._decide(mapping_id, version, "rejected", by=by, why=why)

    def _decide(self, mapping_id: str, version: int, status: Literal["approved", "rejected"], *, by: str,
                why: str) -> MappingDecision:
        check_id("mapping", mapping_id)
        found: list[MappingDecision] = []
        decided: list[MappingEntry] = []

        def decide(lines: list[ChainEntry]) -> list[tuple[str, dict[str, Any]]]:
            entry = next((MappingEntry.model_validate(line.body) for line in lines if line.kind == "entry"
                          and line.body.get("mapping_id") == mapping_id and line.body.get("version") == version), None)
            if entry is None:
                raise KeyError(f"no mapping {mapping_id} version {version}")
            decided.append(entry)
            latest = None
            for line in lines:
                if line.kind == "decision" and line.body.get("mapping_id") == mapping_id and line.body.get("version") == version:
                    latest = MappingDecision.model_validate(line.body)
            if latest is not None and latest.status == status:
                found.append(latest)
                return []
            decision = MappingDecision(mapping_id=mapping_id, version=version, status=status, why=why, by=by, at=_now())
            found.append(decision)
            return [("decision", decision.model_dump(mode="json"))]

        written = self.store.mappings.append_if(decide)
        if written:
            self.store.audit(actor=by, action=f"intake.mapping.{'approve' if status == 'approved' else 'reject'}",
                             resource_id=f"{mapping_id}/{version}",
                             after={"mapping_id": mapping_id, "version": version, "spec_sha256": sha256_of(decided[0].spec),
                                    "row_hash": written[0].hash},
                             reason=why or None)
        return found[0]
