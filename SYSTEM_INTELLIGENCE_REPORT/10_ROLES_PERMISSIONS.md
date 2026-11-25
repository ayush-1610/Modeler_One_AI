# 10 · Roles, access and permissions (post-MAP scope)

All rules below were read in code (`services/api/src/modeler_api/{auth,ownership,memberships,deps,escalations,
signatures_api,campaign_api,read_api,plan_api}.py`, `deploy/keycloak/realm-modeler.json`). Nothing was exercised
against a live Keycloak.

## 1. Identity layers

| Layer | What it holds | Source |
|---|---|---|
| Keycloak realm roles | `modeler-viewer` (read-only), `modeler-curator` (propose values, edit CPFs before signing), `modeler-reviewer` (review and sign MAPs, escalation decisions, CPF acceptance), `modeler-qa` (QA release of the submission bundle), `modeler-admin` (tenant administration) | `deploy/keycloak/realm-modeler.json` |
| Token claims | `tenant_id`, `projects` (admin-editable user attributes), `acr`, `auth_time`, name for the printed signature | `auth.py:40-60` |
| Platform memberships | a project's **owner** and its **members**, kept by the platform and audited | `modeler_project/members.py`; `memberships.py` |
| Deployment kind | development / pilot accept the DEV verifier; production refuses it | `config.py:64-85`; `main.py:44-51` |

Step-up: browser flow "modeler browser" with loa1 (password) and loa2 (password + OTP, `loa-max-age` 0). The API
requires `acr == "loa2"` and `auth_time` ≤ 300 s (`auth.py:23-24, 163-169`). Access tokens live 300 s. One step-up
therefore covers several signatures inside five minutes.

## 2. Rule primitives

| Primitive | Rule | Source |
|---|---|---|
| `Reader` | viewer, curator, reviewer or qa | `deps.py` |
| `Writer` (`Author`) | curator or reviewer | `campaign_api.py:26` |
| `MiddLead` | reviewer | `plan_api.py:68` |
| `require_project` | the project is in the token's or the platform's memberships | `auth.py` |
| `owner_guard` | a write to a `{project_id}` path passes for the owner; on the two signing routes (`POST …/signatures`, `POST …/plan:sign`) also for a reviewer member | `ownership.py:19-35` |
| `may_change(signing)` | `"*"` principal → yes; QA → no; signing and reviewer → yes; else owner or a project with no owner on record | `ownership.py:54-65` |
| `ensure_step_up` | loa2 within 300 s, else 403 `STEP_UP_REQUIRED` / `STEP_UP_STALE` | `auth.py:163-169` |

## 3. Role × action matrix

✓ allowed · ✗ refused by code · - no such action. "Owner" = platform owner of the project.

| Action (route) | viewer member | curator owner | curator member | reviewer owner | reviewer member | QA | admin only | DEV principal |
|---|---|---|---|---|---|---|---|---|
| View campaigns, monitor, escalations, package summary | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (whole company) | ✗ | ✓ |
| Download package / MAR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Sign the MAP via `plan:sign` | ✗ | ✗ (UI offers it) | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ |
| Sign the MAP via generic `POST /signatures` (`map_approval`) | ✓ if owner¹ | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ |
| Start a campaign | ✗ | ✓ | ✗ | ✓ | ✗ (UI offers it) | ✗ | ✗ | ✓ |
| Cancel / stop a running campaign | - | - | - | - | - | - | - | - |
| Abort at an open escalation | ✓ if owner¹ | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ |
| Decide an escalation (retry, accept_best, learn, new_evidence) | ✓ if owner¹ | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ |
| Sign the S4/S5 evaluation (`approve` at the S6 gate) | ✓ if owner¹ | ✓ (self-approval) | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ |
| Sign a MAP deviation (`plan:sign` with pending deviations) | ✗ | ✗ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ |
| Temporal `escalation:decide` / `deviations` | 503 for everyone | | | | | | | |
| Decide on a campaign with no project | any authenticated tenant user, QA included² | | | | | | | |
| `GET /runs/{id}/results` | any authenticated tenant user (no role or project check)² | | | | | | | |
| `/admin/system` (engine check) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ unless admin |
| QA release of the bundle | not implemented (meaning `QA Released` exists, no route uses it) | | | | | | | |

¹ `ensure_owner` checks ownership, not realm roles (`ownership.py:54-65`), and `escalation:resolve` and
`POST /signatures` take `CurrentPrincipal` with no role. An admin can make any user an owner (`admin_api.py:188-215`).
² `escalations.py:236-239`, `read_api.py:148-150`, `results_api.py:34-36`.

## 4. Signed actions in the post-MAP flow

| Signed record | Route | Meaning | What the hash binds | Source |
|---|---|---|---|---|
| MAP (plan path) | `POST /projects/{id}/plan:sign` | Approved | MAP content hash | `plan_api.py:518-601` |
| MAP approval (one-click path) | `POST /projects/{id}/signatures` `record_type=map_approval` | caller-chosen | the prepared MAP file's sha256 | `RunCampaignButton.tsx:39`; `signatures_api.py:26-49` |
| Escalation decision, S4/S5 evaluation, feedback decision | `POST /campaigns/{cid}/stages/{st}/escalation:resolve` | Approved (always, abort included) | sha256 of `campaign:stage:action`, or `decision_digest` with the payload | `escalations.py:258-270`; `feedback.py:280-284` |
| Learn deviation | (inside the decision) the revised MAP is signed with the decision's signature id | Approved | revised MAP content hash | `feedback.py:240-243` |
| MAR, final CPF acceptance, QA release | - | - | - | not built (Temporal workflow has a final-CPF signal, unused) |

Every signature becomes a `signature.create` event on the tenant's hash-chained audit trail, plus a PostgreSQL row in
production (`part11.py`). Campaign starts, stage verdicts and package downloads are not audit events.

## 5. Findings (detail and evidence in 11_TECHNICAL_ASSESSMENT)

1. **No separation of duties.** A curator who owns the project can start a campaign and then sign its escalation
   decisions and its S4/S5 evaluation; the realm description reserves those signatures for reviewers.
2. **The one-click path signs a MAP nobody was shown** and bypasses `plan:sign`'s reviewer-only rule.
3. **The decision action is not checked against the escalation's own options.** `accept_best` sent to the S6 signature
   gate skips the evaluation signature, the D-19 real-data refusal and S6 itself, and runs S7.
4. **Pilot signs with the DEV verifier** while the API listens on `0.0.0.0:8000`; the campaign page does not show the
   deployment kind.
5. **The UI offers actions the API refuses** ("Approve and Sign" to curators, "Run the campaign" to non-owner reviewers).
6. **Temporal decision routes are inert (503) and take a password in the body**, contrary to CLAUDE.md (R-S06).
