# The console redesign: deploy plan and acceptance by use (slice 10)

**Status:** for the owner's review (2026-11-25; brought up to date for the "Graphite" restyle, R1–R4, on 2026-11-27).
Nothing here is done until the owner says so: the deploy needs the
owner's separate go-ahead (the redesign charter: no production change before that), and it is run by the owner from the
Mac, because this plan's author has no access to the server.

Parent plan: `docs/plans/2026-11-23-console-redesign-implementation.md` (§6 slice 10: "full regression, accessibility
and responsive pass, the owner uses it on real work, deploy plan"; exit: the owner's acceptance).

## 1. What goes out
`main` after slice 10 merges: slices 1–10 of the console redesign (#174–#185), the `/templates` retirement (#186), the
"Graphite" restyle (R1 #189, R2 #190, R3 #191 and R4's PR; `design-review/DECISIONS.md` D-I4) and the work merged into
`main` beside them (the data story's Data room phases and groups #187, the Claude API provider, the paid-model cap).

What people will notice:
- **The look ("Graphite"):** near-black ink for actions and the current choice, one blue for charts, source links and
  the focus outline; Plus Jakarta Sans at 15 px, JetBrains Mono for identifiers; rounded panels with soft shadows; the
  sign-in pages (the app's and Keycloak's) in the same look.
- **The console:** no top bar. A sidebar on the grey canvas: the mark to Home, **Start from proposal**, **Search**
  (⌘K / Ctrl K), Home, Your work with its count, Projects, Campaigns; then a project's Overview, its four steps with
  their state, Data plan, Compounds, Documents, History, Agent activity, Members, Settings, Add data (or the Admin
  console for the platform's owner); Help; the person and Sign out at the foot. The page is a white rounded panel whose
  bar holds the breadcrumbs, **notifications** (what waits on the person), Help and whether the API answers. Page tabs are
  underlined and keep their choice in the address; a value's source opens from a blue link.
- **Decisions are asked where the person is:** a bar "A decision is waiting" on the campaign's and its project's pages,
  and a row in Your work, for the people who may decide (R-S02). There is no pop-up on every page any more.
- **New pages:** Your work, Projects, Campaigns, a project's Overview, Data plan, Compounds, Agent activity and a run's
  steps, History in four tabs (Audit trail, Signatures, Versions, Out of date), the admin console's Companies and System
  status (whether the engine answers, R-N08).
- **Inputs:** a study's or product's card opens in a side panel, one at a time (D-I2); confirming a changed card again
  says first what it would change.
- **Review & sign** and **the campaign page** are in tabs; the campaign page has the Package tab.
- **QA** (`modeler-qa`) reads every project of its company and changes or signs none (R-S05).
- **Retired API operations** (no screen used them): `feedback:decide`, `map:generate`, `client-review:edit`, and
  `GET /templates` / `GET /templates/{id}` (their own locked-file PR, approved 2026-11-25).

What does not change: the science (MS-01, rulesets, acceptance criteria, the CPF, the builder, the engine scripts), the
stored records (no migration), the sign-in (Keycloak realm unchanged), Part 11 signing (the token's step-up).

## 2. Before deploying (the owner)
1. **Accept slice 10** (§6 below) and give the go-ahead to deploy.
2. **Push the archive tag** `pre-aws-redesign-20261123-1601` (it exists in the session's checkout; its push was refused
   there). It is the rollback point for the whole web app (`design-review/ARCHIVE.md`).
3. **`main` is green on GitHub** (CI `test`, `lint`, `web`).
4. **Write down what runs now**, the rollback target:
   ```bash
   ssh adt-server 'cat ~/Modeler_One_AI/.deployed.json'
   ```
5. **No script on the server calls a retired operation.** The deploy keeps the server's own `server_e2e*.py` files:
   ```bash
   ssh adt-server 'grep -ln "feedback:decide\|map:generate\|client-review:edit\|/templates" ~/Modeler_One_AI/server_e2e*.py || echo none'
   ```
6. **Keycloak:** the `modeler-qa` realm role is in `deploy/keycloak/realm-modeler.json` (since 2026-11-11). Check it is
   in the server's realm (*Realm roles*) before giving it to anyone; give it as `deploy/keycloak/README.md` §Users says.

## 3. Deploy (from a clean checkout of `main` on the Mac)
```bash
cd ~/Modeler_One_AI
git fetch origin && git checkout main && git pull --ff-only origin main
git status --short          # must print nothing: CLAUDE.md deploys only from a clean main
bash deploy/dev/deploy_to_server.sh
```
The script copies the tree, records the commit (`.deployed.json`), installs, builds the web app, restarts the API and
the web server and prints their status. Then the Installation Qualification, which checks the deployed commit is a
clean `main` (IQ-01) among the rest:
```bash
ssh adt-server 'bash ~/Modeler_One_AI/deploy/server/qualify.sh iq'
```
**Keycloak's sign-in pages** (the username and password page) come from `deploy/keycloak/themes/modeler-one`, which
Keycloak reads from its own folder when it starts. Since 2026-11-27 the deploy script copies them in itself
(`keycloak.sh sync-theme`: only when they changed, the old copy removed first, Keycloak restarted so it shows them;
sign-ins in progress must start again). By hand, for a deploy made before that:
```bash
ssh adt-server 'bash ~/Modeler_One_AI/deploy/server/keycloak.sh sync-theme'
```
Browsers keep Keycloak's theme files for 30 days at an address that changes only with Keycloak's version, so since
2026-11-27 the copy names the stylesheet after its content (`modeler-one-<hash>.css`): a changed look reaches every
browser on its next visit, with no cache to clear. (Before that, a browser that had seen the old page showed the new
page's words in the old navy look, the owner's Safari included.)

## 4. Right after (about 15 minutes; the owner, signed in through Keycloak)
| Check | Where | Expected |
|---|---|---|
| The stack is up | `ssh adt-server 'bash ~/Modeler_One_AI/deploy/server/status_modeler.sh'` | API UP, web UP, Keycloak UP, "Keycloak sign-in" |
| The engine answers | Admin console → System status | the engine is **PK-Sim (OSP suite)** and **it answers** (the check starts `run_job.R` without a job). A software fixture, or "it does not answer", means the engine command is wrong: stop and fix it before anyone runs a campaign |
| Navigation | the sidebar: Start from proposal, Search (⌘K), Home, Your work, Projects, Campaigns, Help | each opens in the console; the page bar's breadcrumbs say where; the bell lists what waits on you |
| The look | any page; then sign out and in | the Graphite look (ink buttons, rounded panels, Plus Jakarta Sans); the username and password page in the same split design as the app's sign-in page (if it shows the older navy card, Keycloak still has the old theme: `keycloak.sh sync-theme`, §3) |
| A project | Overview → each step in the side navigation | each step's state shows; the Waiting on you line links where it is settled |
| Inputs | open a study card | it opens in the side panel; Previous / Next move between cards |
| Review & sign | its tabs | the tab is in the address; a viewer sees it read-only |
| A campaign | Campaigns → one | tabs Stages, Fit, Rounds, Feedback, Package; a software-fixture campaign says so on top |
| Records | History → Signatures; Agent activity | the signatures given on the project's records, escalation decisions included; agent runs and their steps |
| Admin | Admin console → Companies, People, Keys, Models, Limits | the counters and tables open; the pricing switch is in the header |
| Logs | `ssh adt-server 'tail -50 ~/modeler-logs/api.log'` | no new errors |

## 5. Rollback
- **Whole deploy:** redeploy the commit written down in §2.4. On the Mac: `git checkout <that commit>` and
  `bash deploy/dev/deploy_to_server.sh` (it warns that this is not `main`: expected for a rollback), then put `main`
  right (revert, below) and deploy `main` again so IQ-01 passes.
- **One slice:** each slice is one merge commit on `main`; `git revert -m 1 <merge>` undoes it, then deploy `main`.
- **The Graphite look alone:** revert its merges newest first (R4's, then R3 `599989d`, R2 `3b9cbc9`, R1 `ca7903a`) and
  deploy `main`; the console's slices stay (the deploy brings Keycloak's theme back with it, §3).
  Backend changes are additive and separate commits, revertible alone.
- **The web app only:** restore `apps/web` from the tag `pre-aws-redesign-20261123-1601`. The API is compatible with
  the old web app except the retired operations, which the old app did not call either.
- **Data:** nothing to roll back (no migration; the retired operations stored nothing).

## 6. Acceptance by use (the owner's real work)
The slice's exit is the owner's acceptance. Use the console on a real project for a few days; for each task, note what
was slower, unclear or missing (a GitHub issue, or a message to the session), and say "accepted" when none blocks.

| # | Task | Pages | Look for |
|---|---|---|---|
| A1 | Start a project from a real proposal | Start from proposal → Start | the brief's values with their sources; what still needs you, marked where it is |
| A2 | Bring in the client's delivery | Data room → Inputs | each section's word (Done, To confirm, Missing); a card in the side panel; confirming says what it lands |
| A3 | Read what is still needed | Data plan, Inputs → To do | one list of work, each item linked to where it is done |
| A4 | Plan and sign | Review & sign | a study moved and put back (each says what it changes first); the MAP signed with step-up |
| A5 | Run a campaign on PK-Sim | Run → the campaign page | the stages advance; the Fit tab's chart and its table; nothing labelled a software fixture |
| A6 | Decide an escalation | the decision bar or Your work | the decision form with what stopped and why; the signature asked by step-up |
| A7 | Take the package | campaign → Package | reproduction passed, hashes, PK-Sim projects, downloads |
| A8 | Find a record | History, Agent activity, Documents | a signature, a version's changes, a run's steps, a document's pages |
| A9 | Share and settle | Members, Settings | a reviewer added; a test project archived with a reason, then restored |
| A10 | Run the platform | Admin console | Companies, People, Keys, Models, Limits, System status |
| A11 | A QA person's view | signed in as `modeler-qa` | every project of the company readable; no change or signature offered, and refused if tried |
| A12 | On a phone | Your work, a decision, a campaign | the menu opens from the page bar's button; nothing scrolls sideways |
| A13 | The look | a full working day | the type reads comfortably at 15 px; nothing is too faint or too small; say if the Compact view (later, by the owner's choice) is wanted |

## 7. Known limits at acceptance
- `DataTable` and `SortableTable` stay beside `kit/Table` (paging, grouped rows); the stylesheets stay global (B-11).
- Not built yet, by plan: live status without polling (R-N06), the platform audit log page (R-N07), the campaign's Runs
  tab (multi-server only), "waiting since" and "updated" times (no timestamp in the API yet).
- R-S06 (the Temporal path takes a password in the request) must be fixed before any Temporal deployment; today it is
  inert (its verifier answers 503).
- The admin console's pages are checked for accessibility by a signed-in audit, not by CI: the development sign-in in
  the e2e suite does not hold `modeler-admin` (and `auth.py` is locked); `oidc-signing.spec.ts` reaches them under
  Keycloak.
