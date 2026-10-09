"""File-backed read and write stores for the single-node deployment.

This is the persistence seam for the runner-first (no-Docker) execution mode: the whole
create-project → run → report loop is durable as per-tenant JSON under one root, and the same
``ReadStore`` / ``WriteStore`` protocols are what the Postgres §5 read/write tables (T-05) implement
later without changing any caller.

Layout under ``<root>/<tenant>/``::

    projects.json      {"projects":     [ {id, name, compounds, openQuestions, risk, questions?}, ... ]}
    cpf/<compound>.json  a CPF document (pbpk_domain.cpf.CPF)
    studies.json       {"studies":      [ {id, project, ...observed-study fields}, ... ]}
    campaigns.json     {"campaigns":    [ {id, project, compound, stages[], gof?, ...}, ... ]}  (monitor view)
    escalations.json   {"escalations":  [ {id, campaignId, stage, reasonCode, evidence, options[]}, ... ]}
    proposals.json     {"proposals":    [ {id, parameterId, value, unit, quote, reference, agent}, ... ]}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from pbpk_domain.atomic_io import atomic_write_bytes, atomic_write_text, file_lock
from pbpk_domain.cpf import CPF


def resolve_root(root: str) -> Path:
    """A configured read/write root, given as a ``file://`` URI or a plain filesystem path."""
    parsed = urlparse(root)
    return Path(unquote(parsed.path) if parsed.scheme == "file" else root)


class ReadStore(Protocol):
    def list_projects(self, tenant_id: str) -> list[dict[str, Any]]: ...

    def get_project(self, tenant_id: str, project_id: str) -> dict[str, Any] | None: ...

    def get_cpf(self, tenant_id: str, project_id: str, compound: str) -> CPF | None: ...

    def list_campaigns(self, tenant_id: str) -> list[dict[str, Any]]: ...

    def get_campaign(self, tenant_id: str, campaign_id: str) -> dict[str, Any] | None: ...

    def list_escalations(self, tenant_id: str) -> list[dict[str, Any]]: ...

    def list_proposals(self, tenant_id: str) -> list[dict[str, Any]]: ...

    def list_studies(self, tenant_id: str, project_id: str) -> list[dict[str, Any]]: ...

    def get_system(self, tenant_id: str, project_id: str) -> dict[str, Any] | None: ...


class WriteStore(Protocol):
    def put_project(self, tenant_id: str, project: dict[str, Any]) -> None: ...

    def put_cpf(self, tenant_id: str, project_id: str, compound: str, cpf: CPF) -> None: ...

    def put_studies(self, tenant_id: str, project_id: str, studies: list[dict[str, Any]]) -> None: ...

    def put_system(self, tenant_id: str, project_id: str, links: dict[str, Any]) -> None: ...

    def upsert_campaign(self, tenant_id: str, campaign: dict[str, Any]) -> None: ...

    def upsert_escalation(self, tenant_id: str, escalation: dict[str, Any]) -> None: ...

    def upsert_proposal(self, tenant_id: str, proposal: dict[str, Any]) -> None: ...

    def remove_escalation(self, tenant_id: str, escalation_id: str) -> bool: ...


class _FileStoreBase:
    """Shared root resolution and JSON I/O for the file-backed stores."""

    def __init__(self, root: str):
        self.root = resolve_root(root)

    def _read_json(self, path: Path) -> Any | None:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _read_list(self, tenant_id: str, filename: str, key: str) -> list[dict[str, Any]]:
        data = self._read_json(self.root / tenant_id / filename)
        return list(data.get(key, [])) if data else []

    def _write_json(self, path: Path, data: Any) -> None:
        # Atomic (temp file, fsync, os.replace): the campaign runner rewrites these documents from its own thread while
        # the API serves them, and a reader must never see a truncated file.
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


class FileReadStore(_FileStoreBase):
    """Reads the per-tenant JSON documents the web read APIs serve."""

    def list_projects(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._read_list(tenant_id, "projects.json", "projects")

    def get_project(self, tenant_id: str, project_id: str) -> dict[str, Any] | None:
        for project in self.list_projects(tenant_id):
            if project.get("id") == project_id:
                return project
        return None

    def get_cpf(self, tenant_id: str, project_id: str, compound: str) -> CPF | None:
        # a project's own CPF; before 2026-09-24 CPFs were kept per compound for the whole tenant (two projects on one
        # drug overwrote each other), and a project that has no own CPF yet still reads that one
        data = (self._read_json(self.root / tenant_id / "cpf" / project_id / f"{compound}.json")
                or self._read_json(self.root / tenant_id / "cpf" / f"{compound}.json"))
        return CPF.model_validate(data) if data else None

    def list_campaigns(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._read_list(tenant_id, "campaigns.json", "campaigns")

    def get_campaign(self, tenant_id: str, campaign_id: str) -> dict[str, Any] | None:
        for campaign in self.list_campaigns(tenant_id):
            if campaign.get("id") == campaign_id:
                return campaign
        return None

    def list_escalations(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._read_list(tenant_id, "escalations.json", "escalations")

    def list_proposals(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._read_list(tenant_id, "proposals.json", "proposals")

    def list_studies(self, tenant_id: str, project_id: str) -> list[dict[str, Any]]:
        return [s for s in self._read_list(tenant_id, "studies.json", "studies") if s.get("project") == project_id]

    def get_system(self, tenant_id: str, project_id: str) -> dict[str, Any] | None:
        """The project's model-system links (pbpk_domain.system.SystemLinks), or None for a single-compound project."""
        return self._read_json(self.root / tenant_id / "systems" / f"{project_id}.json")


class FileWriteStore(_FileStoreBase):
    """Writes the same per-tenant JSON documents the ``FileReadStore`` reads.

    Collection writes are id-keyed upserts (replace the row with the same ``id``/``campaignId`` or append),
    so the create-project API and the campaign runner can both persist idempotently to one root. Each read-modify-write
    holds the document's lock (``file_lock``), so two threads or processes upserting one collection never lose a row.
    """

    def _upsert(self, tenant_id: str, filename: str, key: str, item: dict[str, Any], *, id_field: str = "id") -> None:
        path = self.root / tenant_id / filename
        with file_lock(path):
            rows = self._read_list(tenant_id, filename, key)
            item_id = item.get(id_field)
            replaced = False
            for index, row in enumerate(rows):
                if row.get(id_field) == item_id:
                    rows[index] = item
                    replaced = True
                    break
            if not replaced:
                rows.append(item)
            self._write_json(path, {key: rows})

    def put_project(self, tenant_id: str, project: dict[str, Any]) -> None:
        self._upsert(tenant_id, "projects.json", "projects", project)

    def put_cpf(self, tenant_id: str, project_id: str, compound: str, cpf: CPF) -> None:
        self._write_json(self.root / tenant_id / "cpf" / project_id / f"{compound}.json", cpf.model_dump(mode="json"))

    def put_system(self, tenant_id: str, project_id: str, links: dict[str, Any]) -> None:
        self._write_json(self.root / tenant_id / "systems" / f"{project_id}.json", links)

    def put_studies(self, tenant_id: str, project_id: str, studies: list[dict[str, Any]]) -> None:
        """Replace this project's studies, leaving other projects' rows untouched."""
        path = self.root / tenant_id / "studies.json"
        with file_lock(path):
            others = [s for s in self._read_list(tenant_id, "studies.json", "studies") if s.get("project") != project_id]
            rows = others + [{**s, "project": project_id} for s in studies]
            self._write_json(path, {"studies": rows})

    def upsert_campaign(self, tenant_id: str, campaign: dict[str, Any]) -> None:
        self._upsert(tenant_id, "campaigns.json", "campaigns", campaign)

    def upsert_escalation(self, tenant_id: str, escalation: dict[str, Any]) -> None:
        self._upsert(tenant_id, "escalations.json", "escalations", escalation)

    def upsert_proposal(self, tenant_id: str, proposal: dict[str, Any]) -> None:
        self._upsert(tenant_id, "proposals.json", "proposals", proposal)

    def remove_escalation(self, tenant_id: str, escalation_id: str) -> bool:
        """Drop a resolved escalation so the review inbox no longer shows it as awaiting a decision. False when it was
        not there: under the document's lock this is the one place a decision is claimed, so of two workers resolving
        the same escalation at once exactly one removes it (phase 8)."""
        path = self.root / tenant_id / "escalations.json"
        with file_lock(path):
            rows = self._read_list(tenant_id, "escalations.json", "escalations")
            kept = [e for e in rows if e.get("id") != escalation_id]
            if len(kept) == len(rows):
                return False
            self._write_json(path, {"escalations": kept})
            return True

    def materialize(self, tenant_id: str, relpath: str, data: bytes) -> Path:
        """Write a raw file under ``<root>/<tenant>/<relpath>`` and return its path (for a file:// URI).

        Used to stage the self-contained campaign inputs (CPF, MAP, observed data) the single-node runner reads.
        """
        path = self.root / tenant_id / relpath
        atomic_write_bytes(path, data)
        return path
