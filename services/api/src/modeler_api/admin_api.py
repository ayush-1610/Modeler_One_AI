"""Who is signed in, and the platform owner's console (docs/plans/2026-11-10-admin-console.md, build A + B).

``GET /me`` answers anyone signed in: who they are, and whether they hold `modeler-admin`, the realm role given to the
platform's owner alone (the web app shows the console only then). ``/admin/*`` answers only that role (403 for anyone
else): every company (tenant) with its people, projects and agent use; one company in full; and the agents' use per
agent, project, person, company and day, each run with who started it (recorded from 2026-11-10).

Read-only. Each look is an audit event (`admin.view`): on the company's own chain when its page is opened, on the
owner's own chain for the overview and the usage, which cover every company.

Costs are estimates: each run's tokens priced at a Claude model's list prices with its conversations cached
(`agent_jobs.recorded_usage`). The tokens are those of the model that ran the agents, so they are a guide to choose a
model and a budget, not an invoice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from modeler_api import agent_jobs
from modeler_api.auth import CurrentPrincipal, Principal, require_role
from modeler_api.config import Settings, SettingsDep
from modeler_api.memberships import archive_for, memberships_for
from modeler_api.part11 import audit_mirror
from modeler_api.responses import answers, envelope
from modeler_api.views.admin import CompanyPage, MeView, Overview, UsagePage
from modeler_contracts.runtime import runtime_env
from modeler_project import FileProjectStore

router = APIRouter(prefix="/api/v1", tags=["admin"])

ADMIN_ROLE = "modeler-admin"
Admin = Annotated[Principal, Depends(require_role(ADMIN_ROLE))]
PricedAs = Literal["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
DEFAULT_PRICE: PricedAs = "claude-opus-5-5"       # the dearest: a budget set from it is not exceeded on the others
NOT_FAILED = ("COMPLETED", "RUNNING")
RUN_LIMIT = 500
# a folder of the store is a company when it holds any of these (its projects, its people, its audit chain, its runs)
_COMPANY_FILES = ("projects.json", "members.json", "audit.jsonl", "agent_runs")


def _root(settings: Settings) -> Path:
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Project storage is not configured. Set MODELER_READ_ROOT.")
    return FileProjectStore(settings.read_root).root


def _companies(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and not d.name.startswith(".") and any((d / f).exists() for f in _COMPANY_FILES))


def _usage(runs: list[dict[str, Any]], priced_as: str) -> dict[str, Any]:
    stamps = [r["started_at"] for r in runs if r["started_at"]]
    return {"runs": len(runs), "failed_runs": sum(1 for r in runs if r["status"] not in NOT_FAILED),
            "input_tokens": sum(r["input_tokens"] for r in runs), "output_tokens": sum(r["output_tokens"] for r in runs),
            "usd": round(float(sum(r["usd"][priced_as] for r in runs)), 4), "last_run_at": max(stamps) if stamps else None}


def _saw(settings: Settings, principal: Principal, tenant_id: str, page: str, **detail: Any) -> None:
    """The look itself, on the audit chain (who, when, which page)."""
    store = FileProjectStore(settings.read_root, audit_mirror=audit_mirror(settings))
    store.audit(tenant_id).append(actor=principal.user_id, action="admin.view", resource_type="tenant",
                                  resource_id=tenant_id, after={"page": page, **detail})


def _projects(settings: Settings, tenant_id: str) -> list[dict[str, Any]]:
    from modeler_storage.filestore import FileReadStore

    return FileReadStore(settings.read_root).list_projects(tenant_id)


@router.get("/me", **answers(MeView))
def me(principal: CurrentPrincipal) -> dict[str, Any]:
    return envelope({"user_id": principal.user_id, "name": principal.printed_name, "tenant_id": principal.tenant_id,
                     "roles": sorted(principal.roles), "admin": ADMIN_ROLE in principal.roles})


@router.get("/admin/overview", **answers(Overview))
def overview(principal: Admin, settings: SettingsDep, priced_as: PricedAs = DEFAULT_PRICE) -> dict[str, Any]:
    root = _root(settings)
    runs = agent_jobs.recorded_usage(root)
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_company[run["tenant_id"]].append(run)
    companies = []
    for tenant_id in _companies(root):
        ids = [p.get("id") for p in _projects(settings, tenant_id)]
        archived = archive_for(settings, tenant_id).archived()
        companies.append({"tenant_id": tenant_id, "people": len(memberships_for(settings, tenant_id).people()),
                          "projects": sum(1 for i in ids if i not in archived),
                          "archived": sum(1 for i in ids if i in archived),
                          "usage": _usage(by_company[tenant_id], priced_as)})
    _saw(settings, principal, principal.tenant_id, "overview")
    return envelope({"companies": companies, "total": _usage(runs, priced_as), "priced_as": priced_as,
                     "system": {"deployment": runtime_env().deployment_kind, "store": True,
                                "agents": agent_jobs.agents_status()}})


@router.get("/admin/companies/{tenant_id}", **answers(CompanyPage))
def company(tenant_id: str, principal: Admin, settings: SettingsDep, priced_as: PricedAs = DEFAULT_PRICE) -> dict[str, Any]:
    root = _root(settings)
    if tenant_id not in _companies(root):
        raise HTTPException(status_code=404, detail=f"no company {tenant_id!r}")
    runs = [r for r in agent_jobs.recorded_usage(root) if r["tenant_id"] == tenant_id]
    memberships = memberships_for(settings, tenant_id)
    archived = archive_for(settings, tenant_id).archived()
    projects = []
    for p in _projects(settings, tenant_id):
        pid = str(p.get("id"))
        gone = archived.get(pid)
        projects.append({"id": pid, "name": str(p.get("name") or pid), "compounds": [str(c) for c in p.get("compounds") or []],
                         "archived": gone is not None, "archived_reason": gone.reason if gone else None,
                         "members": [m.name for m in memberships.members(pid)],
                         "usage": _usage([r for r in runs if r["project_id"] == pid], priced_as)})
    people = [{"subject": person.subject, "name": person.name, "projects": sorted(memberships.projects_of(person.subject)),
               "usage": _usage([r for r in runs if r["started_by"] == person.subject], priced_as)}
              for person in memberships.people()]
    _saw(settings, principal, tenant_id, "company")
    return envelope({"tenant_id": tenant_id, "people": people, "projects": projects, "usage": _usage(runs, priced_as),
                     "priced_as": priced_as})


def _grouped(runs: list[dict[str, Any]], key: Callable[[dict[str, Any]], str], label: Callable[[str], str],
             priced_as: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        groups[key(run)].append(run)
    rows = [{"key": k, "label": label(k), "usage": _usage(group, priced_as)} for k, group in groups.items()]
    return sorted(rows, key=lambda row: (-row["usage"]["usd"], -row["usage"]["input_tokens"], row["key"]))


def _names(settings: Settings, tenants: Iterable[str]) -> dict[tuple[str, str], str]:
    return {(t, p.subject): p.name for t in tenants for p in memberships_for(settings, t).people()}


@router.get("/admin/usage", **answers(UsagePage))
def usage(principal: Admin, settings: SettingsDep, since: date | None = None, tenant_id: str | None = None,
          priced_as: PricedAs = DEFAULT_PRICE, limit: int = RUN_LIMIT) -> dict[str, Any]:
    root = _root(settings)
    start = datetime(since.year, since.month, since.day, tzinfo=UTC) if since else None
    runs = [r for r in agent_jobs.recorded_usage(root, start) if tenant_id is None or r["tenant_id"] == tenant_id]
    runs.sort(key=lambda r: r["started_at"] or "", reverse=True)
    names = _names(settings, {r["tenant_id"] for r in runs})
    projects = {(t, str(p.get("id"))): str(p.get("name") or p.get("id")) for t in {r["tenant_id"] for r in runs}
                for p in _projects(settings, t)}

    def person(r: dict[str, Any]) -> str:
        return f"{r['tenant_id']}/{r['started_by']}" if r["started_by"] else "-"

    def project(r: dict[str, Any]) -> str:
        return f"{r['tenant_id']}/{r['project_id']}" if r["project_id"] else "-"

    def person_label(key: str) -> str:
        if key == "-":
            return "not recorded (runs before 2026-11-10)"
        tenant, subject = key.split("/", 1)
        return f"{names.get((tenant, subject), subject)} ({tenant})"

    def project_label(key: str) -> str:
        if key == "-":
            return "no project"
        tenant, pid = key.split("/", 1)
        return f"{projects.get((tenant, pid), pid)} ({tenant})"

    _saw(settings, principal, principal.tenant_id, "usage", since=since.isoformat() if since else None,
         company=tenant_id)
    shown = max(1, min(limit, RUN_LIMIT))
    return envelope({
        "since": since.isoformat() if since else None, "tenant_id": tenant_id, "priced_as": priced_as,
        "prices": agent_jobs.claude_prices()[priced_as], "total": _usage(runs, priced_as),
        "by_agent": _grouped(runs, lambda r: r["agent"], str, priced_as),
        "by_project": _grouped(runs, project, project_label, priced_as),
        "by_person": _grouped(runs, person, person_label, priced_as),
        "by_company": _grouped(runs, lambda r: r["tenant_id"], str, priced_as),
        "by_day": sorted(_grouped(runs, lambda r: (r["started_at"] or "-")[:10], str, priced_as),
                         key=lambda row: row["key"], reverse=True),
        "runs": [{**{k: r[k] for k in ("run_id", "tenant_id", "project_id", "agent", "model", "status", "started_at",
                                       "started_by", "turns", "input_tokens", "output_tokens")},
                  "started_by_name": names.get((r["tenant_id"], r["started_by"])) if r["started_by"] else None,
                  "usd": round(float(r["usd"][priced_as]), 6)} for r in runs[:shown]],
        "limit": shown,
    })
