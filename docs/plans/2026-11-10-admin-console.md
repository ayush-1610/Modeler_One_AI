# The admin console, and the agents on Claude through Amazon Bedrock (2026-11-10)

The owner, 2026-11-10: an admin page "only to me" that can "see through the data and everything about the users, its
projects", to "make sure everything at the user side is smooth and running"; from it, "switching between different
models that different agents use, their limits of usage, tracking their usage, project as well as user wise";
"creating the users, groups, tenants, companies"; and "the API keys ... so that I must be able to rotate keys timely
without touching the backend", with "routines, tracking, checking and rotations all ... from this admin panel".

The owner's decisions the same day (on the move to Claude, `CHANGELOG` 2026-11-10 usage report):
- the agents move to Claude on **Amazon Bedrock**;
- client documents going to AWS is accepted;
- the agents call Bedrock through Anthropic's own SDK (`anthropic[bedrock]`, its `AnthropicBedrockMantle` client),
  not through the LiteLLM proxy: decided here with the owner's delegation ("make this decision yourself making sure
  that we have all control and tracking"), because only the SDK gives prompt caching, effort, strict tool schemas and
  each call's exact usage (cached tokens included) to track.

---

## 1. What the platform has today

| Area | Today |
|---|---|
| Identity | Keycloak realm `modeler`; realm roles `modeler-viewer`, `-curator`, `-reviewer`, `-qa`, `-admin` (`-admin` used nowhere); the token carries the person's tenant; no groups; people are created in Keycloak's own console; no code calls Keycloak's admin API. |
| Tenants | The token's `tenant_id`; the file store keeps each tenant's projects in its own folder; the Part 11 mirror in PostgreSQL has `tenants` and `users` tables with row-level security. |
| Projects | Per tenant; each with its members; each person who signs in is remembered (`modeler_project.members`); a project is archived with a reason, never deleted. |
| Agents | One model for every agent, set only in the server's environment (`MODELER_LLM_PROVIDER`, `LITELLM_*`); each run records its turns' tokens (`agent_runs/*/run.json`, `steps.jsonl`), its cost field always 0, and not who started it. |
| Keys | `~/.modeler-secrets.env` on the server, read at start; a change needs a restart. |
| Health | `/health`, the doctor, the qualification checks (`deploy/server/qualify.sh`). |

## 2. The console

**Who.** Only the platform's owner: the realm role `modeler-admin`, given to the owner alone in Keycloak. The API
refuses everyone else (403); the web app shows the console only to that role. Every change made from the console
also needs a fresh step-up (the TOTP code a signature asks for). Every look into another tenant's data, and every
change, is an event on the platform's audit log: who, when, what, and why for a change.

**Where.** `/admin` in the web app; `/api/v1/admin/*` in the API (its own router; it reads the tenants' stores
through their owner modules, as the other routers do).

**What, in the order it is built:**

| | Module | What it does |
|---|---|---|
| A | Overview | Every company (tenant): its people, its projects (active, archived), its agent runs (finished, failed) and their tokens and cost; system health. |
| B | Usage and cost | Each agent run's model, tokens (input, output, cache write, cache read) and cost at that model's price; who started it; totals per agent, project, person, company and day; CSV export. |
| C | Models and agents | Per agent: provider (Bedrock, the in-house model, off), model, effort, turn cap, text limits, fallback model; a "test" call. Each change is versioned and each run records the settings it ran with (for the report). |
| D | Keys | Provider credentials (AWS for Bedrock, the in-house proxy, web search, Keycloak's service account) kept encrypted in the platform's store under one master key that stays in the server's environment; write-only (shown as their last 4 characters, who added them, when); rotation: add, test, make active, retire the old, with a reminder when a key is old. A change takes effect without a restart. |
| E | Limits | A monthly spend and token limit per company, project and person: a warning at 80 %; at 100 % agents stop starting (or warn only: question 2). |
| F | People and companies | Through Keycloak's admin API with a service account: companies created and disabled; people created (Keycloak sends them the set-password email), disabled, given roles and their company; groups; project memberships. |
| G | Routines | Scheduled checks, each with its last result and "run now": keys' age, spend against limits, failed runs, the engine, backups, Keycloak and PostgreSQL. |
| H | Support view | Any project opened read-only as its people see it ("view as"), to see what they see. |

A and B are built first (one PR); C and D come with the switch to Bedrock (the agents then read their model and keys
from the console); E to H follow.

### Not built, and why (from the checklist the owner pasted)

- **Acting as a user (impersonation):** no. Part 11 needs every record and signature to name the person who made it;
  "view as" (H) shows what they see, read-only.
- **The administrator setting or resetting a password:** no. Passwords are never typed, stored or sent by the platform
  (CLAUDE.md); the console asks Keycloak to send the reset email or to require a new password at the next sign-in.
- **Deleting database rows, people or companies:** no. The audit chain is append-only and projects are archived with
  a reason (page review 1); people and companies are disabled, never erased.
- **FAQ and static pages, email templates, maintenance mode:** not asked for this product's work; later if wanted.

### Locked files

A, B, C, G and H need none: they use `auth.require_role` and `auth.ensure_step_up` as they are. D keeps its records
in the file store (no migration) unless PostgreSQL is wanted. F needs a service-account client in the Keycloak realm
file (not locked). The console needs the `modeler-admin` role on the owner's Keycloak sign-in; the development sign-in
(`auth.DevVerifier`, DEV ONLY, locked) does not hold it, so a pilot deployment signing in with it cannot open the
console. Giving it the role (one locked change, in its own PR) would show every company's data to anyone who reaches a
pilot, so the console is meant for a deployment with Keycloak (question 5).

## 3. Questions for the owner

1. The administrator's role: the existing `modeler-admin`, given to you alone? (Assumed in A and B.)
2. A limit reached: stop the agents, or warn only?
3. Keys: in the platform's own store, encrypted under one master key in the server's environment (works on the
   current server), or AWS Secrets Manager (needs the server to reach AWS and an IAM identity there)?
4. Groups: what are they for: a team inside a company that shares its projects?
5. Where will you open the console: on the server once Keycloak signs people in (you hold `modeler-admin`), or on the
   pilot's development sign-in too (the locked change above, which opens it to anyone who reaches the pilot)?

## 4. Builds

- **A + B (branch `admin-console`), built:** `GET /api/v1/me` (who is signed in, whether an administrator);
  `GET /api/v1/admin/overview` (every company: people, active and archived projects, agent runs, failed runs, tokens,
  estimated cost; the deployment and the agents' model), `/admin/companies/{tenant}` (its people with their projects
  and use, its projects with their members, state and use), `/admin/usage?since=&tenant_id=&priced_as=` (per agent,
  project, person, company and day, and the runs, newest first). Costs are each run's recorded tokens at a Claude
  model's list prices with caching (`agent_jobs.recorded_usage`). Every look is an `admin.view` audit event (a
  company's page on its own chain; the overview and usage on the owner's). Each agent run now records who started it:
  `jobs.start(by=...)` names the person to everything the job runs (`jobs.started_by`), and `AgentRun` writes it to
  `run.json` (`started_by`); earlier runs read as "not recorded". The web app: `/admin`, `/admin/companies/[tenant]`,
  `/admin/usage`, and a "Platform" link in the sidebar for `modeler-admin` only.
