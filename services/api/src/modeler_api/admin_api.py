"""Who is signed in, and the platform owner's console (docs/plans/2026-11-10-admin-console.md, builds A to D).

``GET /me`` answers anyone signed in: who they are, and whether they hold `modeler-admin`, the realm role given to the
platform's owner alone (the web app shows the console only then). ``/admin/*`` answers only that role (403 for anyone
else): every company (tenant) with its people, projects and agent use; one company in full; and the agents' use per
agent, project, person, company and day, each run with who started it (recorded from 2026-11-10).

Each look is an audit event (`admin.view`): on the company's own chain when its page is opened, on the owner's own
chain for the overview and the usage, which cover every company. The console changes only the platform's own settings
(`platform_settings`): each agent's model and the providers' keys. Every change needs a fresh step-up (the TOTP a
signature asks for) and a reason, and is an audit event on the owner's chain naming the key by its last 4 characters,
never its secret.

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
from pydantic import BaseModel, Field

from modeler_api import agent_jobs
from modeler_api import platform_settings as ps
from modeler_api.auth import CurrentPrincipal, Principal, ensure_step_up, require_role
from modeler_api.config import Settings, SettingsDep
from modeler_api.memberships import archive_for, memberships_for
from modeler_api.part11 import audit_mirror
from modeler_api.responses import answers, envelope
from modeler_api.views.admin import AgentsPage, CompanyPage, KeysPage, MeView, Overview, UsagePage
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
                  if d.is_dir() and not d.name.startswith((".", "_")) and any((d / f).exists() for f in _COMPANY_FILES))


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


# --- C: each agent's model -----------------------------------------------------------------------------------------


class AgentSet(BaseModel):
    provider: str
    model: str = ""
    reason: str = Field(min_length=1)


class KeyAdd(BaseModel):
    """A key to store. Every field is optional to the validator and checked by the handler, so a refusal never echoes the
    request (FastAPI's 422 answer repeats the input it rejects, which here holds a secret)."""

    provider: str = ""
    label: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    reason: str = ""


class KeyChange(BaseModel):
    reason: str = Field(min_length=1)


def _changed(settings: Settings, principal: Principal, action: str, resource_id: str, *, after: Any,
             reason: str, before: Any = None) -> None:
    """A change to the platform's settings, on the owner's audit chain."""
    store = FileProjectStore(settings.read_root, audit_mirror=audit_mirror(settings))
    store.audit(principal.tenant_id).append(actor=principal.user_id, action=action, resource_type="platform",
                                            resource_id=resource_id, before=before, after=after, reason=reason)


def _refused(exc: ps.SettingsError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _agents_page(settings: Settings) -> dict[str, Any]:
    store, keys = ps.AgentSettings(settings.read_root), ps.KeyStore(settings.read_root, settings.master_key)
    doc = store.doc()
    active = {r["provider"] for r in keys.records() if r["state"] == "active"}
    rows = []
    for agent, label in ps.AGENTS.items():
        setting = doc["current"].get(agent) or {}
        provider = setting.get("provider", "environment")
        rows.append({"agent": agent, "label": label, "provider": provider, "provider_label": ps.AGENT_PROVIDERS[provider],
                     "model": setting.get("model", ""), "set_by": setting.get("by"), "set_at": setting.get("at"),
                     "reason": setting.get("reason"), "runs_on": agent_jobs.agents_status(agent)})
    return envelope({
        "agents": rows,
        "providers": [{"id": p, "label": label, "needs_model": p in ps.KEY_PROVIDERS, "has_active_key": p in active}
                      for p, label in ps.AGENT_PROVIDERS.items()],
        "environment": agent_jobs.agents_status(),
        "history": [{k: h[k] for k in ("agent", "provider", "model", "by", "at", "reason")}
                    for h in reversed(doc["history"][-50:])],
    })


@router.get("/admin/agents", **answers(AgentsPage))
def agents(principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    _root(settings)
    return _agents_page(settings)


@router.put("/admin/agents/{agent}", **answers(AgentsPage))
def set_agent(agent: str, body: AgentSet, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    _root(settings)
    ensure_step_up(principal)
    store = ps.AgentSettings(settings.read_root)
    before = store.current(agent)
    try:
        setting = store.set(agent, body.provider, body.model, by=principal.user_id, reason=body.reason)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    _changed(settings, principal, "admin.agent.set", agent, reason=body.reason,
             before={k: before[k] for k in ("provider", "model")} if before else None,
             after={k: setting[k] for k in ("provider", "model")})
    return _agents_page(settings)


# --- D: the providers' keys ----------------------------------------------------------------------------------------


def _keys_page(settings: Settings) -> dict[str, Any]:
    keys = ps.KeyStore(settings.read_root, settings.master_key)
    try:
        ps.cipher(settings.master_key)
        problem = None
    except ps.SettingsError as exc:
        problem = str(exc)
    return envelope({
        "keys": keys.view(),
        "providers": [{"id": p, "label": spec["label"],
                       "fields": [{"name": n, "label": label, "secret": secret, "required": required}
                                  for n, label, secret, required in spec["fields"]]}
                      for p, spec in ps.KEY_PROVIDERS.items()],
        "master_key": problem is None, "master_problem": problem, "rotate_after_days": ps.ROTATE_AFTER_DAYS,
    })


def _key_named(record: dict[str, Any]) -> dict[str, Any]:
    """A key as the audit trail names it: never a secret."""
    return {"provider": record["provider"], "label": record["label"], "state": record["state"],
            "last4": {f: v["last4"] for f, v in record["secret"].items()}}


@router.get("/admin/keys", **answers(KeysPage))
def keys(principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    _root(settings)
    return _keys_page(settings)


@router.post("/admin/keys", **answers(KeysPage))
def add_key(body: KeyAdd, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    _root(settings)
    ensure_step_up(principal)
    if not body.reason.strip():
        raise HTTPException(status_code=409, detail="say why the key is added (kept with the change)")
    try:
        record = ps.KeyStore(settings.read_root, settings.master_key).add(body.provider, body.label, body.fields,
                                                                          by=principal.user_id)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    _changed(settings, principal, "admin.key.add", record["id"], after=_key_named(record), reason=body.reason)
    return _keys_page(settings)


def _record(store: ps.KeyStore, key_id: str) -> dict[str, Any]:
    record = next((r for r in store.records() if r["id"] == key_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no key {key_id!r}")
    return record


@router.post("/admin/keys/{key_id}:test", **answers(KeysPage))
def test_key(key_id: str, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    _root(settings)
    store = ps.KeyStore(settings.read_root, settings.master_key)
    _record(store, key_id)
    try:
        provider, fields = store.fields(key_id)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    ok, message = agent_jobs.test_key(provider, fields)
    store.record_test(key_id, ok, message)
    return _keys_page(settings)


@router.post("/admin/keys/{key_id}:activate", **answers(KeysPage))
def activate_key(key_id: str, body: KeyChange, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    _root(settings)
    ensure_step_up(principal)
    store = ps.KeyStore(settings.read_root, settings.master_key)
    _record(store, key_id)
    try:
        record, replaced = store.activate(key_id)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    _changed(settings, principal, "admin.key.activate", key_id, after=_key_named(record) | {"retired": replaced},
             reason=body.reason)
    return _keys_page(settings)


@router.post("/admin/keys/{key_id}:retire", **answers(KeysPage))
def retire_key(key_id: str, body: KeyChange, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    _root(settings)
    ensure_step_up(principal)
    store = ps.KeyStore(settings.read_root, settings.master_key)
    _record(store, key_id)
    try:
        record = store.retire(key_id)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    _changed(settings, principal, "admin.key.retire", key_id, after=_key_named(record), reason=body.reason)
    return _keys_page(settings)
