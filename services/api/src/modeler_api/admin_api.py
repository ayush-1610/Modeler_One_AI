"""Who is signed in, and the platform owner's console (docs/plans/2026-11-10-admin-console.md, builds A to E).

``GET /me`` answers anyone signed in: who they are, and whether they hold `modeler-admin`, the realm role given to the
platform's owner alone (the web app shows the console only then). ``/admin/*`` answers only that role (403 for anyone
else): every company (tenant) with its people, projects and agent use; one company in full; and the agents' use per
agent, project, person, company and day, each run with who started it (recorded from 2026-11-10).

Each look is an audit event (`admin.view`): on the company's own chain when its page is opened, on the owner's own
chain for the overview, the usage and the limits, which cover every company. The console changes only the platform's
own settings (`platform_settings`): each agent's model, the providers' keys and the monthly limits. Every change needs a
fresh step-up (the TOTP a signature asks for) and a reason, and is an audit event on the owner's chain naming a key by
its last 4 characters, never its secret.

A monthly limit (E) on a company's, a project's or a person's agent use warns the administrator at 80 % and when it is
reached (the overview and the Limits page); it never stops an agent, and the companies' people never see it (answer 2).

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
from modeler_api import keycloak_admin as kc
from modeler_api import platform_settings as ps
from modeler_api.auth import CurrentPrincipal, Principal, ensure_step_up, require_role
from modeler_api.config import Settings, SettingsDep
from modeler_api.memberships import archive_for, memberships_for
from modeler_api.part11 import audit_mirror
from modeler_api.responses import answers, envelope
from modeler_api.views.admin import (
    AgentsPage,
    CompanyPage,
    KeysPage,
    LimitsPage,
    MeView,
    Overview,
    PeoplePage,
    PipelineHealth,
    UsagePage,
)
from modeler_contracts.runtime import runtime_env
from modeler_project import FileProjectStore, intake_health
from modeler_project.members import MembershipError

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
    registry = ps.CompanyRegistry(settings.read_root)
    for tenant_id in _companies(root):
        ids = [p.get("id") for p in _projects(settings, tenant_id)]
        archived = archive_for(settings, tenant_id).archived()
        named = registry.get(tenant_id) or {}
        companies.append({"tenant_id": tenant_id, "name": named.get("name") or "", "disabled": bool(named.get("disabled")),
                          "people": len(memberships_for(settings, tenant_id).people()),
                          "projects": sum(1 for i in ids if i not in archived),
                          "archived": sum(1 for i in ids if i in archived),
                          "usage": _usage(by_company[tenant_id], priced_as)})
    _saw(settings, principal, principal.tenant_id, "overview")
    month, limits = _limit_rows(settings, priced_as)
    return envelope({"companies": companies, "total": _usage(runs, priced_as), "priced_as": priced_as,
                     "system": {"deployment": runtime_env().deployment_kind, "store": True,
                                "agents": agent_jobs.agents_status()},
                     "month": month, "warnings": [row for row in limits if row["level"] != "ok"]})


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
    named = ps.CompanyRegistry(settings.read_root).get(tenant_id) or {}
    return envelope({"tenant_id": tenant_id, "name": named.get("name") or "",
                     "disabled_reason": (named.get("disabled") or {}).get("reason"), "people": people,
                     "projects": projects, "usage": _usage(runs, priced_as), "priced_as": priced_as})


class GiveProjects(BaseModel):
    """`to`: who receives them (someone who has signed in to the company); `from_`: whose projects they are, or empty
    for every project of the company (those made before memberships were kept, or outside the web, included)."""

    to: str = Field(min_length=1)
    from_: str = Field("", alias="from")
    owner: bool = False        # and make them each project's owner, the only one who changes it
    reason: str = Field(min_length=1)


@router.post("/admin/companies/{tenant_id}:give-projects", **answers(CompanyPage))
def give_projects(tenant_id: str, body: GiveProjects, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    """Make a person a member of another person's projects, or of all the company's, and with `owner` their owner: how
    the projects made under the pilot's DEV sign-in (its "dev-user") reach the people who sign in through Keycloak. Each
    membership and change of owner is an audit event on the company's chain, by the administrator, with the reason."""
    root = _root(settings)
    if tenant_id not in _companies(root):
        raise HTTPException(status_code=404, detail=f"no company {tenant_id!r}")
    ensure_step_up(principal)
    memberships = memberships_for(settings, tenant_id)
    if body.from_ and body.from_ == body.to:
        raise HTTPException(status_code=409, detail="a person already has their own projects")
    ids = sorted(memberships.projects_of(body.from_)) if body.from_ else sorted(
        str(p["id"]) for p in _projects(settings, tenant_id) if p.get("id"))
    if not ids:
        raise HTTPException(status_code=409, detail="there are no projects to give")
    whose = f"the projects of {body.from_}" if body.from_ else "every project of the company"
    why = f"admin console: {whose}: {body.reason.strip()}"
    try:
        for project_id in ids:
            memberships.add(project_id, body.to, by=principal.user_id, reason=why)
            if body.owner:
                memberships.set_owner(project_id, body.to, by=principal.user_id, reason=why)
    except MembershipError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return company(tenant_id, principal, settings, DEFAULT_PRICE)


def _grouped(runs: list[dict[str, Any]], key: Callable[[dict[str, Any]], str], label: Callable[[str], str],
             priced_as: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        groups[key(run)].append(run)
    rows = [{"key": k, "label": label(k), "usage": _usage(group, priced_as)} for k, group in groups.items()]
    return sorted(rows, key=lambda row: (-row["usage"]["usd"], -row["usage"]["input_tokens"], row["key"]))


def _names(settings: Settings, tenants: Iterable[str]) -> dict[tuple[str, str], str]:
    return {(t, p.subject): p.name for t in tenants for p in memberships_for(settings, t).people()}


@router.get("/admin/pipeline", **answers(PipelineHealth))
def pipeline_health(principal: Admin, settings: SettingsDep, since: date | None = None) -> dict[str, Any]:
    """Where the intake pipeline is blind, per company and in all (contracts 2026-11-12 §8.10): the files by state, the
    share of tables mapped from the cache, by a rule, by the LLM and left unread, parser failures, unsupported files by
    extension, outside items, unresolved anchors, pages needing OCR, and each stage's median and 90th-percentile time.
    Counts from the pipeline's own run lines only: no file name, no value. `since`: the runs queued from that day."""
    root = _root(settings)
    start = datetime(since.year, since.month, since.day, tzinfo=UTC) if since else None
    found = intake_health.summary(root, since=start)
    registry = ps.CompanyRegistry(settings.read_root)
    companies = [{**row, "name": (registry.get(row["tenant"]) or {}).get("name") or ""} for row in found["companies"]]
    _saw(settings, principal, principal.tenant_id, "pipeline", since=since.isoformat() if since else None)
    return envelope({**found, "companies": companies})


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
    effort: str = ""          # Claude: low … max (empty: the model's own default)
    fallback: str = ""        # Claude: the model asked when the first declines or stays overloaded
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
                     "model": setting.get("model", ""), "effort": setting.get("effort", ""),
                     "fallback": setting.get("fallback", ""), "set_by": setting.get("by"), "set_at": setting.get("at"),
                     "reason": setting.get("reason"), "runs_on": agent_jobs.agents_status(agent)})
    return envelope({
        "agents": rows,
        "providers": [{"id": p, "label": label, "needs_model": p in ps.KEY_PROVIDERS, "has_active_key": p in active}
                      for p, label in ps.AGENT_PROVIDERS.items()],
        "environment": agent_jobs.agents_status(),
        "efforts": list(ps.EFFORTS), "claude_models": list(agent_jobs.CLAUDE_MODELS),
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
        setting = store.set(agent, body.provider, body.model, by=principal.user_id, reason=body.reason,
                            effort=body.effort, fallback=body.fallback)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    _changed(settings, principal, "admin.agent.set", agent, reason=body.reason,
             before={k: before.get(k, "") for k in ("provider", "model", "effort", "fallback")} if before else None,
             after={k: setting[k] for k in ("provider", "model", "effort", "fallback")})
    return _agents_page(settings)


@router.put("/admin/agents", **answers(AgentsPage))
def set_every_agent(body: AgentSet, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    """Put every agent on one provider and model in one step (the owner, 2026-11-11: "I must be able to switch between
    any of them easily", for when Claude on Bedrock is lost and the in-house model takes over, or back). Each agent's
    change is its own audit event with the same reason. Refused, with nothing changed, when the provider has no active
    key: a switch made in a hurry must not leave every agent with nothing to run on."""
    _root(settings)
    ensure_step_up(principal)
    store = ps.AgentSettings(settings.read_root)
    if body.provider in ps.KEY_PROVIDERS:
        active = {r["provider"] for r in ps.KeyStore(settings.read_root, settings.master_key).records() if r["state"] == "active"}
        if body.provider not in active:
            raise HTTPException(status_code=409, detail=f"{ps.AGENT_PROVIDERS[body.provider]} has no active key: add one under "
                                                        "Keys and make it active first; no agent was changed")
    fields = ("provider", "model", "effort", "fallback")
    try:
        for agent in ps.AGENTS:
            before = store.current(agent)
            setting = store.set(agent, body.provider, body.model, by=principal.user_id, reason=body.reason,
                                effort=body.effort, fallback=body.fallback)
            _changed(settings, principal, "admin.agent.set", agent, reason=body.reason,
                     before={k: before.get(k, "") for k in fields} if before else None,
                     after={k: setting[k] for k in fields} | {"every_agent": True})
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
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
    ok, message = kc.test_key(settings, fields) if provider == "keycloak" else agent_jobs.test_key(provider, fields)
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


# --- E: monthly limits, a warning to the administrator only ----------------------------------------------------------


class LimitSet(BaseModel):
    """A limit on a company (`subject` empty), a project (its id) or a person (their subject), each month: the estimated
    spend in USD and the tokens in and out. A measure left empty has no limit; both empty removes the limit."""

    scope: Literal["company", "project", "person"]
    tenant_id: str = Field(min_length=1)
    subject: str = ""
    usd: float | None = None
    tokens: int | None = None
    reason: str = Field(min_length=1)


def _month(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def _share(used: float, limit: float | None) -> float | None:
    return round(used / limit, 4) if limit else None


def _limit_rows(settings: Settings, priced_as: str, now: datetime | None = None) -> tuple[str, list[dict[str, Any]]]:
    """This month's use against each limit (calendar month, UTC), the fullest first."""
    root = _root(settings)
    start = _month(now)
    limits = ps.LimitSettings(settings.read_root).doc()["limits"]
    if not limits:
        return start.strftime("%Y-%m"), []
    runs = agent_jobs.recorded_usage(root, start)
    tenants = {limit["tenant_id"] for limit in limits.values()}
    names = _names(settings, tenants)
    projects = {(t, str(p.get("id"))): str(p.get("name") or p.get("id")) for t in tenants for p in _projects(settings, t)}
    rows = []
    for key, limit in limits.items():
        tenant, scope, subject = limit["tenant_id"], limit["scope"], limit["subject"]
        mine = [r for r in runs if r["tenant_id"] == tenant and (
            scope == "company" or (scope == "project" and r["project_id"] == subject)
            or (scope == "person" and r["started_by"] == subject))]
        used_usd = round(float(sum(r["usd"][priced_as] for r in mine)), 4)
        used_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in mine)
        usd_share, tokens_share = _share(used_usd, limit["usd"]), _share(used_tokens, limit["tokens"])
        top = max(s for s in (usd_share, tokens_share, 0.0) if s is not None)
        label = tenant if scope == "company" else (
            f"{projects.get((tenant, subject), subject)} ({tenant})" if scope == "project"
            else f"{names.get((tenant, subject), subject)} ({tenant})")
        rows.append({"id": key, "scope": scope, "tenant_id": tenant, "subject": subject, "label": label,
                     "usd": limit["usd"], "tokens": limit["tokens"], "used_usd": used_usd, "used_tokens": used_tokens,
                     "usd_share": usd_share, "tokens_share": tokens_share,
                     "level": "over" if top >= 1 else "warn" if top >= ps.WARN_AT else "ok",
                     "set_by": limit["by"], "set_at": limit["at"], "reason": limit["reason"], "_top": top})
    rows.sort(key=lambda row: (-row["_top"], row["id"]))
    return start.strftime("%Y-%m"), [{k: v for k, v in row.items() if k != "_top"} for row in rows]


def _limits_page(settings: Settings, priced_as: str) -> dict[str, Any]:
    month, rows = _limit_rows(settings, priced_as)
    targets = []
    for tenant_id in _companies(_root(settings)):
        projects = [{"id": str(p["id"]), "name": str(p.get("name") or p["id"])} for p in _projects(settings, tenant_id) if p.get("id")]
        people = [{"subject": p.subject, "name": p.name} for p in memberships_for(settings, tenant_id).people()]
        if projects or people:                       # the owner's own folder (only the console's audit trail) is not one
            targets.append({"tenant_id": tenant_id, "projects": projects, "people": people})
    history = ps.LimitSettings(settings.read_root).doc()["history"]
    return envelope({"month": month, "priced_as": priced_as, "warn_at": ps.WARN_AT, "limits": rows,
                     "warnings": [row for row in rows if row["level"] != "ok"],
                     "history": [{k: h[k] for k in ("id", "usd", "tokens", "by", "at", "reason")} for h in reversed(history[-50:])],
                     "targets": targets})


@router.get("/admin/limits", **answers(LimitsPage))
def limits(principal: Admin, settings: SettingsDep, priced_as: PricedAs = DEFAULT_PRICE) -> dict[str, Any]:
    page = _limits_page(settings, priced_as)
    _saw(settings, principal, principal.tenant_id, "limits")
    return page


@router.put("/admin/limits", **answers(LimitsPage))
def set_limit(body: LimitSet, principal: Admin, settings: SettingsDep, priced_as: PricedAs = DEFAULT_PRICE) -> dict[str, Any]:
    """Set, change or remove a monthly limit (a fresh step-up and a reason; an audit event on the owner's chain)."""
    root = _root(settings)
    ensure_step_up(principal)
    if body.tenant_id not in _companies(root):
        raise HTTPException(status_code=404, detail=f"no company {body.tenant_id!r}")
    known = {"project": {str(p.get("id")) for p in _projects(settings, body.tenant_id)},
             "person": {p.subject for p in memberships_for(settings, body.tenant_id).people()}}
    if body.scope in known and body.subject.strip() and body.subject.strip() not in known[body.scope]:
        raise HTTPException(status_code=409, detail=f"{body.tenant_id} has no {body.scope} {body.subject!r}")
    try:
        before, after = ps.LimitSettings(settings.read_root).set(body.scope, body.tenant_id, body.subject, usd=body.usd,
                                                                  tokens=body.tokens, by=principal.user_id, reason=body.reason)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    measures = ("usd", "tokens")
    key = ps.limit_id(body.scope, body.tenant_id, body.subject.strip())
    _changed(settings, principal, "admin.limit.set" if after else "admin.limit.remove", key, reason=body.reason,
             before={k: before[k] for k in measures} if before else None,
             after={k: after[k] for k in measures} if after else None)
    return _limits_page(settings, priced_as)


# --- F: people and companies (kept in Keycloak; `keycloak_admin`) ----------------------------------------------------


def _on_chain(settings: Settings, principal: Principal, tenant_id: str, action: str, resource_type: str,
              resource_id: str, *, after: Any, reason: str, before: Any = None) -> None:
    """A change to a company or one of its people, on that company's own audit chain."""
    store = FileProjectStore(settings.read_root, audit_mirror=audit_mirror(settings))
    store.audit(tenant_id).append(actor=principal.user_id, action=action, resource_type=resource_type,
                                  resource_id=resource_id, before=before, after=after, reason=reason)


def _when(ms: Any) -> str | None:
    return datetime.fromtimestamp(int(ms) / 1000, UTC).isoformat() if ms else None


def _person(directory: kc.Directory, p: dict[str, Any]) -> dict[str, Any]:
    return {"id": p["id"], "username": p["username"], "name": f"{p['first_name']} {p['last_name']}".strip() or p["username"],
            "email": p["email"], "tenant_id": p["tenant_id"], "roles": [r for r in kc.SHOWN_ROLES if r in p["roles"]],
            "enabled": p["enabled"], "authenticator": p["authenticator"], "required_actions": p["required_actions"],
            "created_at": _when(p.get("created_ms")), "console_link": directory.console_link(p["id"], "settings")}


def _people_page(directory: kc.Directory, settings: Settings, tenant_id: str | None = None, *,
                 notice: str | None = None, link: str | None = None) -> dict[str, Any]:
    companies = _companies(_root(settings))
    page = {"ready": False, "problem": directory.problem, "smtp": False, "service_client": kc.SERVICE_CLIENT,
            "roles": list(kc.ROLES), "companies": companies, "people": [], "notice": notice, "notice_link": link}
    if directory.problem:
        return envelope(page)
    try:
        people, smtp = directory.people(), directory.smtp()
    except kc.DirectoryError as exc:
        return envelope(page | {"problem": str(exc)})
    rows = [_person(directory, p) for p in people if tenant_id is None or p["tenant_id"] == tenant_id]
    rows.sort(key=lambda r: (r["tenant_id"], r["name"].lower()))
    return envelope(page | {"ready": True, "smtp": smtp, "people": rows})


def _refused_by(exc: kc.DirectoryError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _find(directory: kc.Directory, user_id: str) -> dict[str, Any]:
    try:
        person = next((p for p in directory.people() if p["id"] == user_id), None)
    except kc.DirectoryError as exc:
        raise _refused_by(exc) from exc
    if person is None:
        raise HTTPException(status_code=404, detail=f"no person {user_id!r} in the realm")
    return person


def _company_open(settings: Settings, tenant_id: str) -> None:
    if tenant_id not in _companies(_root(settings)):
        raise HTTPException(status_code=409, detail=f"there is no company {tenant_id!r}: add it first (Overview)")
    if (ps.CompanyRegistry(settings.read_root).get(tenant_id) or {}).get("disabled"):
        raise HTTPException(status_code=409, detail=f"the company {tenant_id!r} is disabled: enable it first")


def _roles_given(roles: list[str]) -> list[str]:
    unknown = sorted(set(roles) - set(kc.ROLES))
    if unknown:
        raise HTTPException(status_code=409, detail=f"the console gives only {', '.join(kc.ROLES)} (not {', '.join(unknown)}); "
                                                    "modeler-admin stays with the platform's owner")
    return [r for r in kc.ROLES if r in roles]


class PersonNew(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._@-]*$")
    email: str = Field(min_length=3, max_length=200)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    tenant_id: str
    roles: list[str] = Field(default_factory=lambda: ["modeler-viewer", "modeler-curator"])
    reason: str = Field(min_length=1)


class PersonChange(BaseModel):
    """What changes: whether they can sign in, roles given or taken, their company. Omitted: unchanged."""

    enabled: bool | None = None
    add_roles: list[str] = Field(default_factory=list)
    remove_roles: list[str] = Field(default_factory=list)
    tenant_id: str | None = None
    reason: str = Field(min_length=1)


class PersonReset(BaseModel):
    """A lost authenticator (removed; set up again at the next sign-in) and/or a forgotten password (Keycloak's email
    link, or a temporary one set by the owner in Keycloak's console: the platform never handles it)."""

    password: bool = False
    authenticator: bool = False
    reason: str = Field(min_length=1)


class CompanyNew(BaseModel):
    tenant_id: str
    name: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1)


class CompanyChange(BaseModel):
    reason: str = Field(min_length=1)


@router.get("/admin/people", **answers(PeoplePage))
def people(principal: Admin, settings: SettingsDep, directory: kc.DirectoryDep, tenant_id: str | None = None) -> dict[str, Any]:
    page = _people_page(directory, settings, tenant_id)
    _saw(settings, principal, principal.tenant_id, "people", company=tenant_id)
    return page


@router.post("/admin/people", **answers(PeoplePage))
def add_person(body: PersonNew, principal: Admin, settings: SettingsDep, directory: kc.DirectoryDep) -> dict[str, Any]:
    """A new person of a company, in Keycloak: they set their own password and authenticator at their first sign-in."""
    _root(settings)
    ensure_step_up(principal)
    _company_open(settings, body.tenant_id)
    roles = _roles_given(body.roles)
    if not roles or "@" not in body.email:
        raise HTTPException(status_code=409, detail="a person needs an email address and at least one role")
    try:
        user_id = directory.create(username=body.username, email=body.email.strip(), first_name=body.first_name.strip(),
                                   last_name=body.last_name.strip(), tenant_id=body.tenant_id, roles=roles)
    except kc.DirectoryError as exc:
        raise _refused_by(exc) from exc
    name = f"{body.first_name.strip()} {body.last_name.strip()}"
    _on_chain(settings, principal, body.tenant_id, "admin.person.add", "person", user_id, reason=body.reason,
              after={"username": body.username, "name": name, "email": body.email.strip(), "tenant_id": body.tenant_id,
                     "roles": roles})
    notice, link = _first_password(directory, user_id, name, body.email.strip(), list(kc.FIRST_SIGN_IN))
    return _people_page(directory, settings, notice=notice, link=link)


def _first_password(directory: kc.Directory, user_id: str, name: str, email: str, actions: list[str]) -> tuple[str, str | None]:
    """Keycloak emails the person their link when it has a mail server; else the owner sets a temporary password in
    Keycloak's own console (the link). Either way the platform never sees a password."""
    try:
        if directory.smtp():
            directory.email_actions(user_id, actions)
            what = "password and authenticator" if "CONFIGURE_TOTP" in actions else "password"
            return f"Keycloak emailed {name} ({email}) a link, valid 12 hours, to set their {what}.", None
        problem = "Keycloak has no mail server, so it cannot email them."
    except kc.DirectoryError as exc:
        problem = f"Keycloak could not email them ({exc})."
    told = (f"{problem} Open their page in Keycloak (the link), Credentials → Set password, Temporary on, and give the "
            f"temporary password to {name} yourself (in person or by phone, never by this platform). At their first "
            "sign-in they choose their own and set up their authenticator.")
    return told, directory.console_link(user_id)


@router.post("/admin/people/{user_id}:change", **answers(PeoplePage))
def change_person(user_id: str, body: PersonChange, principal: Admin, settings: SettingsDep,
                  directory: kc.DirectoryDep) -> dict[str, Any]:
    _root(settings)
    ensure_step_up(principal)
    person = _find(directory, user_id)
    yourself = user_id == principal.user_id
    if yourself and (body.enabled is False or (body.tenant_id and body.tenant_id != person["tenant_id"])):
        raise HTTPException(status_code=409, detail="you cannot disable yourself or move yourself to another company "
                                                    "from the console (do it in Keycloak's own console)")
    add = [r for r in _roles_given(body.add_roles) if r not in person["roles"]]
    remove = [r for r in _roles_given(body.remove_roles) if r in person["roles"]]
    moving = body.tenant_id is not None and body.tenant_id != person["tenant_id"]
    if moving:
        _company_open(settings, body.tenant_id or "")
    enabling = body.enabled is not None and body.enabled != person["enabled"]
    if not (add or remove or moving or enabling):
        raise HTTPException(status_code=409, detail="nothing to change")
    try:
        if enabling:
            directory.set_enabled(user_id, bool(body.enabled))
        if add or remove:
            directory.set_roles(user_id, add=add, remove=remove)
        if moving:
            directory.set_tenant(user_id, body.tenant_id or "")
    except kc.DirectoryError as exc:
        raise _refused_by(exc) from exc
    before = {"enabled": person["enabled"], "roles": person["roles"], "tenant_id": person["tenant_id"]}
    after = {"enabled": body.enabled if enabling else person["enabled"],
             "roles": sorted((set(person["roles"]) | set(add)) - set(remove)),
             "tenant_id": body.tenant_id if moving else person["tenant_id"], "username": person["username"]}
    for tenant in {person["tenant_id"], after["tenant_id"]} - {""}:
        _on_chain(settings, principal, tenant, "admin.person.change", "person", user_id, before=before, after=after,
                  reason=body.reason)
    return _people_page(directory, settings)


@router.post("/admin/people/{user_id}:reset", **answers(PeoplePage))
def reset_person(user_id: str, body: PersonReset, principal: Admin, settings: SettingsDep,
                 directory: kc.DirectoryDep) -> dict[str, Any]:
    _root(settings)
    ensure_step_up(principal)
    if not (body.password or body.authenticator):
        raise HTTPException(status_code=409, detail="choose the password, the authenticator or both")
    person = _find(directory, user_id)
    name = f"{person['first_name']} {person['last_name']}".strip() or person["username"]
    removed = 0
    notice, link = None, None
    try:
        if body.authenticator:
            removed = directory.remove_authenticator(user_id)
            directory.require(user_id, ["CONFIGURE_TOTP"])
            notice = f"{name}'s authenticator is removed; they set up a new one at their next sign-in."
    except kc.DirectoryError as exc:
        raise _refused_by(exc) from exc
    if body.password:
        told, link = _first_password(directory, user_id, name, person["email"], ["UPDATE_PASSWORD"])
        notice = f"{notice} {told}" if notice else told
    _on_chain(settings, principal, person["tenant_id"] or principal.tenant_id, "admin.person.reset", "person", user_id,
              reason=body.reason, after={"username": person["username"], "authenticators_removed": removed,
                                         "password": ("link given to set it in Keycloak" if link else "emailed")
                                         if body.password else None})
    return _people_page(directory, settings, notice=notice, link=link)


@router.post("/admin/companies", **answers(CompanyPage))
def add_company(body: CompanyNew, principal: Admin, settings: SettingsDep) -> dict[str, Any]:
    """A new company (a tenant): its folder in the store, its name, and its own audit chain from its first event."""
    root = _root(settings)
    ensure_step_up(principal)
    if not kc.TENANT_ID.match(body.tenant_id):
        raise HTTPException(status_code=409, detail="a company's id is 2 to 40 lowercase letters, digits or hyphens "
                                                    "(it is the tenant its people carry and cannot change later)")
    if body.tenant_id in _companies(root):
        raise HTTPException(status_code=409, detail=f"the company {body.tenant_id!r} exists already")
    try:
        ps.CompanyRegistry(settings.read_root).add(body.tenant_id, body.name, by=principal.user_id)
    except ps.SettingsError as exc:
        raise _refused(exc) from exc
    _on_chain(settings, principal, body.tenant_id, "admin.company.add", "tenant", body.tenant_id, reason=body.reason,
              after={"name": body.name.strip()})
    return company(body.tenant_id, principal, settings, DEFAULT_PRICE)


@router.post("/admin/companies/{tenant_id}:disable", **answers(CompanyPage))
def disable_company(tenant_id: str, body: CompanyChange, principal: Admin, settings: SettingsDep,
                    directory: kc.DirectoryDep) -> dict[str, Any]:
    """Every person of the company can no longer sign in (their sessions end as their tokens expire); its projects,
    records and people are kept, and enabling it lets the same people in again."""
    root = _root(settings)
    ensure_step_up(principal)
    if tenant_id not in _companies(root):
        raise HTTPException(status_code=404, detail=f"no company {tenant_id!r}")
    if tenant_id == principal.tenant_id:
        raise HTTPException(status_code=409, detail="this is your own company: disabling it would lock you out")
    if (ps.CompanyRegistry(settings.read_root).get(tenant_id) or {}).get("disabled"):
        raise HTTPException(status_code=409, detail=f"the company {tenant_id!r} is disabled already")
    try:
        members = [p for p in directory.people() if p["tenant_id"] == tenant_id and p["enabled"]]
        for person in members:
            directory.set_enabled(person["id"], False)
    except kc.DirectoryError as exc:
        raise _refused_by(exc) from exc
    ps.CompanyRegistry(settings.read_root).disable(tenant_id, [p["id"] for p in members], by=principal.user_id,
                                                  reason=body.reason)
    _on_chain(settings, principal, tenant_id, "admin.company.disable", "tenant", tenant_id, reason=body.reason,
              after={"people_disabled": sorted(p["username"] for p in members)})
    return company(tenant_id, principal, settings, DEFAULT_PRICE)


@router.post("/admin/companies/{tenant_id}:enable", **answers(CompanyPage))
def enable_company(tenant_id: str, body: CompanyChange, principal: Admin, settings: SettingsDep,
                   directory: kc.DirectoryDep) -> dict[str, Any]:
    root = _root(settings)
    ensure_step_up(principal)
    if tenant_id not in _companies(root):
        raise HTTPException(status_code=404, detail=f"no company {tenant_id!r}")
    registry = ps.CompanyRegistry(settings.read_root)
    if not (registry.get(tenant_id) or {}).get("disabled"):
        raise HTTPException(status_code=409, detail=f"the company {tenant_id!r} is not disabled")
    people_ids = list((registry.get(tenant_id) or {})["disabled"].get("people") or [])
    try:
        for user_id in people_ids:
            directory.set_enabled(user_id, True)
    except kc.DirectoryError as exc:
        raise _refused_by(exc) from exc
    registry.enable(tenant_id)
    _on_chain(settings, principal, tenant_id, "admin.company.enable", "tenant", tenant_id, reason=body.reason,
              after={"people_enabled": len(people_ids)})
    return company(tenant_id, principal, settings, DEFAULT_PRICE)
