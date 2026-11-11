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
    name: str
    disabled: bool
    people: int
    projects: int
    archived: int
    usage: Usage


class PlatformState(View):
    deployment: str
    store: bool
    agents: AgentsStatus


class LimitRow(View):
    """One monthly limit and this month's use against it (spend at the page's prices, tokens in and out). `level`:
    `ok` below `warn_at` of every measure, `warn` from there, `over` once a measure is reached. A limit only warns."""

    id: str
    scope: str
    tenant_id: str
    subject: str
    label: str
    usd: float | None
    tokens: int | None
    used_usd: float
    used_tokens: int
    usd_share: float | None
    tokens_share: float | None
    level: str
    set_by: str
    set_at: str
    reason: str


class Overview(View):
    """Every company (tenant) with its people, projects and agent use; the platform's state; the limits this month's use
    has reached 80 % of, or passed (`warnings`, for the administrator only)."""

    companies: list[CompanyRow]
    total: Usage
    priced_as: str
    system: PlatformState
    month: str
    warnings: list[LimitRow]


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
    """One company: its people (each who has signed in) and its projects, archived ones included; its name, and why it is
    disabled when it is."""

    tenant_id: str
    name: str
    disabled_reason: str | None
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
    effort: str
    fallback: str
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
    """`efforts` and `claude_models`: the choices for an agent on Claude (Bedrock's model ids)."""

    agents: list[AgentRow]
    providers: list[AgentProvider]
    environment: AgentsStatus
    history: list[AgentChange]
    efforts: list[str]
    claude_models: list[str]


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


class LimitChange(View):
    id: str
    usd: float | None
    tokens: int | None
    by: str
    at: str
    reason: str


class LimitTargetProject(View):
    id: str
    name: str


class LimitTargetPerson(View):
    subject: str
    name: str


class LimitTarget(View):
    """A company, with the projects and people a limit can be set on."""

    tenant_id: str
    projects: list[LimitTargetProject]
    people: list[LimitTargetPerson]


class LimitsPage(View):
    """The monthly limits (console, E): each with this month's use; those at 80 % or past; the changes; what a limit can
    be set on. A limit warns the administrator and never stops an agent; the companies' people never see it."""

    month: str
    priced_as: str
    warn_at: float
    limits: list[LimitRow]
    warnings: list[LimitRow]
    history: list[LimitChange]
    targets: list[LimitTarget]


class PersonView(View):
    """A person of the realm as Keycloak keeps them: their company (`tenant_id`), roles, whether they can sign in and
    have set up their authenticator, and what Keycloak will ask of them at their next sign-in."""

    id: str
    username: str
    name: str
    email: str
    tenant_id: str
    roles: list[str]
    enabled: bool
    authenticator: bool
    required_actions: list[str]
    created_at: str | None
    console_link: str


class PeoplePage(View):
    """The console's people (F). `ready` false: Keycloak is not set up for the console, `problem` says what to do.
    `smtp`: Keycloak can email a person their set-password link; without it the owner sets a first password in
    Keycloak's own console (`notice_link`). Passwords never pass through the platform."""

    ready: bool
    problem: str | None
    smtp: bool
    service_client: str
    roles: list[str]
    companies: list[str]
    people: list[PersonView]
    notice: str | None
    notice_link: str | None
