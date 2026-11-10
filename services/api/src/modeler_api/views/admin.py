"""Answers of `admin_api`: who is signed in, and the platform owner's console (docs/plans/2026-11-10-admin-console.md)."""

from __future__ import annotations

from modeler_api.views.common import AgentsStatus, View


class MeView(View):
    """The signed-in person: what the web app shows them (the console's link only to the platform's owner)."""

    user_id: str
    name: str
    tenant_id: str
    roles: list[str]
    admin: bool


class Usage(View):
    """Agent runs and their tokens; `usd`: what they would cost on the Claude model the page is priced at, with their
    conversations cached (an estimate: the tokens are the model's that ran them)."""

    runs: int
    failed_runs: int
    input_tokens: int
    output_tokens: int
    usd: float
    last_run_at: str | None


class CompanyRow(View):
    tenant_id: str
    people: int
    projects: int
    archived: int
    usage: Usage


class PlatformState(View):
    deployment: str
    store: bool
    agents: AgentsStatus


class Overview(View):
    """Every company (tenant) with its people, projects and agent use; the platform's state."""

    companies: list[CompanyRow]
    total: Usage
    priced_as: str
    system: PlatformState


class PersonRow(View):
    subject: str
    name: str
    projects: list[str]
    usage: Usage


class ProjectRow(View):
    id: str
    name: str
    compounds: list[str]
    archived: bool
    archived_reason: str | None
    members: list[str]
    usage: Usage


class CompanyPage(View):
    """One company: its people (each who has signed in) and its projects, archived ones included."""

    tenant_id: str
    people: list[PersonRow]
    projects: list[ProjectRow]
    usage: Usage
    priced_as: str


class UsageRun(View):
    run_id: str
    tenant_id: str
    project_id: str | None
    agent: str
    model: str
    status: str
    started_at: str | None
    started_by: str | None
    started_by_name: str | None
    turns: int
    input_tokens: int
    output_tokens: int
    usd: float


class UsageGroup(View):
    key: str
    label: str
    usage: Usage


class UsagePage(View):
    """Agent use since a date, per agent, project, person, company and day, and the runs themselves (newest first, at
    most `limit`). `prices`: USD per million tokens of `priced_as` (input, cache write, cache read, output)."""

    since: str | None
    tenant_id: str | None
    priced_as: str
    prices: dict[str, float]
    total: Usage
    by_agent: list[UsageGroup]
    by_project: list[UsageGroup]
    by_person: list[UsageGroup]
    by_company: list[UsageGroup]
    by_day: list[UsageGroup]
    runs: list[UsageRun]
    limit: int


class AgentRow(View):
    """One agent's model as the console sets it ("environment": the server's own configuration), and what it runs on
    now (`runs_on`, the model the next run would take, or why none)."""

    agent: str
    label: str
    provider: str
    provider_label: str
    model: str
    set_by: str | None
    set_at: str | None
    reason: str | None
    runs_on: AgentsStatus


class AgentProvider(View):
    id: str
    label: str
    needs_model: bool
    has_active_key: bool


class AgentChange(View):
    agent: str
    provider: str
    model: str
    by: str
    at: str
    reason: str


class AgentsPage(View):
    agents: list[AgentRow]
    providers: list[AgentProvider]
    environment: AgentsStatus
    history: list[AgentChange]


class KeyField(View):
    name: str
    label: str
    secret: bool
    required: bool


class KeyProvider(View):
    id: str
    label: str
    fields: list[KeyField]


class KeyView(View):
    """A stored key, never its secret: the secret fields' last 4 characters and the plain fields (an address, a
    region). `due`: active for `rotate_after_days` or longer."""

    id: str
    provider: str
    label: str
    state: str
    plain: dict[str, str]
    last4: dict[str, str]
    added_by: str
    added_at: str
    activated_at: str | None
    retired_at: str | None
    tested_at: str | None
    test_ok: bool | None
    test_message: str | None
    active_days: int | None
    due: bool


class KeysPage(View):
    keys: list[KeyView]
    providers: list[KeyProvider]
    master_key: bool
    master_problem: str | None
    rotate_after_days: int
