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
| E | Limits | A monthly spend and token limit per company, project and person: a warning to the administrator at 80 % and at 100 %; agents are never stopped (answer 2). |
| F | People and companies | Through Keycloak's admin API with a service account: companies created and disabled; people created (Keycloak sends them the set-password email), disabled, given roles and their company; groups; project memberships. |
| G | Routines | Scheduled checks, each with its last result and "run now": keys' age, spend against limits, failed runs, the engine, backups, Keycloak and PostgreSQL. |
| H | Support view | Any project opened read-only as its people see it ("view as"), to see what they see. |

A and B are built first (one PR); then C and D (the agents read their model and keys from the console), then the
Claude-on-Bedrock provider the console can choose, then E to H. Answer 4's ownership rule is its own PR (built, §4).

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

## 3. The owner's answers (2026-11-10, revision 2 of this plan)

1. **The role:** `modeler-admin`, held by the owner alone. "Admin is god of platform with everything": the console
   does everything the platform can do, within the three limits in §2 (Part 11: nobody acts as another person, no
   password passes through the platform, no record is erased).
2. **Limits:** they warn the administrator; nothing stops ("client will see and decide later what to show them"). A
   company's people see nothing of them yet.
3. **Keys:** in the platform's own store, encrypted under one master key in the server's environment, seen and
   changed only from the console.
4. **Companies, people and projects:** a company holds many people; each person holds many projects; a project can
   be shared with others of the same company. Its creator is its **owner**, the only one who edits it; the people it
   is shared with **read** it ("as maintaining the log will be difficult at this stage"). More access management
   later.
5. **Where:** on the server with Keycloak (option A); the development sign-in keeps no console (no locked change).

6. **Signing a shared project** (asked from answer 4, answered "yes" the same day): a person a project is shared with,
   holding the reviewer role, still signs its MAP and settles its escalations (an approval by a second person, which
   ICH M15 and Part 11 review expect); every other change stays the owner's.

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
- **C + D (branch `admin-models-keys`):** each agent's model chosen in the console (provider, model, effort; "as the
  server's environment says" until set), every change with its reason and step-up, the history kept; provider keys in
  the platform store, AES-GCM under `MODELER_MASTER_KEY`, write-only (shown by their last 4 characters), each added,
  tested, made active (the previous one retired), retired; a key older than 90 days is flagged for rotation. The
  agents read their model and the active key at the start of each run, so a change needs no restart.
- **Claude on Amazon Bedrock (branch `bedrock-provider`):** a provider the console's Models page offers per agent,
  with a model (`anthropic.claude-opus-5-5`, `-sonnet-5-5`, `-haiku-5-5`), an effort and a fallback model, on the
  active Bedrock key (`modeler_agents.claude`, Anthropic's SDK `AnthropicBedrockMantle`): prompt caching of the system
  prompt, tools and conversation; effort as Claude's `output_config.effort`; each assistant turn sent back as the model
  wrote it (thinking included); a refusal re-asked of the fallback model by the SDK's client-side middleware (Bedrock
  has no server-side fallback) and an overloaded model retried once on it; every turn's cache writes and reads
  recorded, and the usage report prices them as they were. Not yet: the agents' text and page limits, set for the
  in-house model's context, widened for Claude; the A1 and delivery evaluations run on Opus 5.5 against Sonnet 5.5.
- **Going live on Keycloak (branch `keycloak-go-live`):** the realm imported with the web's Tailscale address among
  `modeler-web`'s redirect URIs; the console's "Give a person projects" (a person's projects, or every project of the
  company, to a person who has signed in once), with a step-up and an audit event per membership.
- **Answers 4 and 6, the ownership rule (branch `ownership-rule`, on `keycloak-go-live`):** the creator is the owner,
  kept in `members.json` and recorded on the audit chain; every write to a project is its owner's alone (`NOT_OWNER`);
  a reviewer it is shared with signs its MAP, its records and its campaigns' escalations; the owner stays a member; the
  console's "Give a person projects" can make the person the owner. Not yet: the pages marked read-only for the people
  a project is shared with (their edit buttons answer with the refusal).
- **E, limits (branch `limit-warnings`):** a monthly limit on the agents' estimated spend (USD) and tokens (in and
  out), on a company, a project or a person, kept in the platform store (`_platform/limits.json`, with every change).
  This calendar month's use (UTC) is measured against each, at the page's Claude prices (Opus 5.5 unless another is
  chosen, so a budget is not exceeded on the cheaper models). At 80 % of a measure the administrator is warned, and
  again when it is reached: a banner on the console's overview and on its Limits page (`/admin/limits`), where limits
  are set, changed and removed, each with a reason and a fresh step-up, an `admin.limit.set` or `admin.limit.remove`
  audit event on the owner's chain. Nothing stops an agent, and no answer outside `/admin` carries a limit (answer 2).
  Not yet: a warning sent to the administrator (email or push) rather than shown in the console; that comes with the
  routines (G).
- **Switch every agent (branch `agents-switch-all`, 2026-11-11):** the owner may lose access to Claude on Bedrock, so
  the Models page puts all five agents on one provider and model in one step (back to the in-house model, or onto
  Claude again), each agent's change audited with the same reason; refused when the provider has no active key.
- **F, people and companies (branch `admin-people`, 2026-11-11):** the realm's people from Keycloak's admin API as the
  service account `modeler-admin-api` (least privilege: `realm-management` view-realm, view-users, query-users,
  manage-users; its secret under Keys): add a person to a company with roles (they set their own password and
  authenticator: Keycloak's email when it has a mail server, else a temporary password the owner sets in Keycloak's
  own console, linked from the page), change roles, move, disable or enable, reset a lost authenticator; add a
  company (named), disable it (its people) and enable it again. `modeler-admin` stays out of the console; the owner
  cannot lock themselves out. Not yet: groups or teams within a company (deferred with the access management the
  owner left for later, answer 4).
