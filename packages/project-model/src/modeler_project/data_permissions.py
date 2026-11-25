"""Where a company's client files may be sent for an AI model to read (the governance review of model failover,
2026-11-22, requirements 1-4 and 13).

One record per company (tenant), kept by an administrator on Admin → Companies for all of its people and projects at
once (the owner, 2026-11-24: the setting is not shown to the company's people; it was a per-project panel on the Data
room before). A company starts in-house only: its files go to no cloud service, whatever model an agent is set to or
falls back on. A cloud service is allowed only with a recorded permission: who recorded it and when, the basis (the
client's written consent, by its reference) and when it ends. "The owner's word is not the client's consent": the
record names the client's own document. Every change is audited on the company's chain and kept in its history.

The gate itself (`allows`) is applied where an agent's model is built for a project's work
(`modeler_api.agent_jobs.project_model`): a model the project's company does not allow is left out, and with none left
the work stops and says what to record. The per-project records the earlier panel wrote
(`<tenant>/projects/<id>/data_permissions.json`) are no longer read: every company is in-house only until an
administrator records its permission here.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from modeler_project.workspace import Workspace
from pbpk_domain.atomic_io import file_lock

#: the services an agent's model may run on, as the admin console names them; the in-house model keeps files on the
#: server and needs no permission
CLOUD_SERVICES: dict[str, str] = {
    "groq": "GroqCloud",
    "nvidia": "NVIDIA API catalog",
    "bedrock": "Claude on Amazon Bedrock",
    # Anthropic's own Claude API (the owner, 2026-11-24, D6): like NVIDIA and Groq, a client's files go to it only with
    # the client's written permission recorded here; for a company of made-up demo data the record names that instead
    "anthropic": "Claude API (Anthropic)",
    "openai_compat": "another OpenAI-compatible service",
}
IN_HOUSE = ("litellm",)


class PermissionError_(ValueError):
    """A permission the rules refuse (a service not known, no reference, an end before today)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def service_label(provider: str) -> str:
    return CLOUD_SERVICES.get(provider, "the in-house model" if provider in IN_HOUSE else provider)


class DataPermissions:
    """A company's record of where its client files may be sent (every project of the company follows it)."""

    def __init__(self, store: Any, tenant_id: str):
        self.store, self.tenant_id = store, tenant_id
        root = getattr(store, "root", None)
        self.path: Path | None = Path(root) / tenant_id / "data_permissions.json" if root else None

    @classmethod
    def of(cls, ws: Workspace) -> DataPermissions:
        """The record that governs a project's files: its company's."""
        return cls(ws.store, ws.tenant_id)

    def doc(self) -> dict[str, Any]:
        if self.path is None or not self.path.exists():
            return {"in_house_only": True, "services": {}, "history": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def allows(self, provider: str, today: date | None = None) -> bool:
        """Whether the company's files may go to `provider` today: a cloud service (`CLOUD_SERVICES`, where every
        new cloud provider must be named) only with a permission in force; anything else keeps the files here."""
        if provider not in CLOUD_SERVICES:       # the in-house model, a test double: no file leaves the server
            return True
        doc = self.doc()
        grant = doc["services"].get(provider)
        if doc.get("in_house_only", True) or grant is None:
            return False
        ends = grant.get("expires") or ""
        return not ends or (today or datetime.now(UTC).date()).isoformat() <= ends

    def set(self, *, in_house_only: bool, services: dict[str, dict[str, str]], by: str, reason: str) -> dict[str, Any]:
        """Record the company's permissions as a whole (each service: its basis, the client's reference, its end)."""
        if not reason.strip():
            raise PermissionError_("a change needs a reason")
        clean: dict[str, dict[str, str]] = {}
        for provider, grant in services.items():
            if provider not in CLOUD_SERVICES:
                raise PermissionError_(f"unknown service {provider!r}; one of: {', '.join(CLOUD_SERVICES)}")
            reference = (grant.get("reference") or "").strip()
            if not reference:
                raise PermissionError_(f"{CLOUD_SERVICES[provider]}: name the client's written permission (its reference)")
            ends = (grant.get("expires") or "").strip()
            if ends:
                try:
                    if date.fromisoformat(ends) < datetime.now(UTC).date():
                        raise PermissionError_(f"{CLOUD_SERVICES[provider]}: the permission ended on {ends}")
                except ValueError as exc:
                    if isinstance(exc, PermissionError_):
                        raise
                    raise PermissionError_(f"{CLOUD_SERVICES[provider]}: the end date {ends!r} is not a date (YYYY-MM-DD)") from exc
            clean[provider] = {"basis": (grant.get("basis") or "the client's written consent").strip(),
                               "reference": reference, "expires": ends, "by": by, "at": _now()}
        if self.path is None:
            raise PermissionError_("this company has no file store to keep its permissions in")
        with file_lock(self.path):
            before = self.doc()
            entry = {"in_house_only": in_house_only, "services": clean, "by": by, "at": _now(), "reason": reason.strip()}
            doc = {"in_house_only": in_house_only, "services": clean, "history": [*before.get("history", []), entry]}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        self.store.audit(self.tenant_id).append(
            actor=by, action="company.data_permissions.set", resource_type="tenant", resource_id=self.tenant_id,
            before={"in_house_only": before.get("in_house_only", True), "services": sorted(before.get("services", {}))},
            after={"in_house_only": in_house_only, "services": {p: g["reference"] for p, g in clean.items()}},
            reason=reason.strip())
        return doc
