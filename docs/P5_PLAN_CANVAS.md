# P5 · Model plan canvas (review layer L3) — integration

Status: built 2026-10-05 (T-50), plan `docs/plans/2026-09-25-project-startup-pipeline.md` §11, decisions D-07, D-12,
D-13, D-14, D-15. This page says how the canvas hooks into the existing routes and artifacts, what each rule is, and
where the build departs from the plan.

## 1. Where it sits

```
P4 inputs (accepted)                      P5 model plan                                   P6 run
CPF/main ─────────────┐                                                          
STUDY_CATALOG/main ───┼──► MODEL_PLAN/main vN ──(validator green, MIDD lead signs)──► MAP/main ──► POST /campaigns
READINESS/main ───────┘     (derived from all three:          generate_map(split=plan)      (signed MAP, campaign CPF,
DISSOLUTION/* (view)         an input change makes it STALE)  + Part 11 step-up signature    observed PK with origins)
```

* **Default = today's engine.** `plan.build_default` runs `split_studies` (MS-01 §3.3) and `generate_map` exactly as
  `campaign:prepare` does; each study's role comes from the MAP's own rules (`campaign.map.training_stages`, the one
  helper added to `map.py`). Fit candidates per stage are `STAGE_PLAN` resolved against CPF v1; budgets are
  `BUDGET_FRACTION`. Test: with no change, the MAP from the plan has the same content hash as `generate_map`.
* **MAP from plan.** `plan.map_from_plan` turns the plan's placements into a `SplitResult` and calls `generate_map`
  unchanged; the plan's fit choices become fit policies of the campaign CPF (`plan.campaign_cpf`); every change and
  its reason is appended to the MAP's split rationale ("Plan change: …"), every acknowledged warning to its
  limitations. No second planning engine exists.

## 2. Data model (`modeler_project.plan.ModelPlan`, artifact MODEL_PLAN/main)

| Field | Content |
|---|---|
| `studies` | per study: class, score, route, dose, food, design, n, origin, whether it has a profile, `default_role`, `new` |
| `placements` | study → `{role, by, userLocked, reason, at}`; role ∈ S1 · S2 · S3 (trains; INTERNAL) · S5 (EXTERNAL) · S6 (application, EXTERNAL) · SUPPORTIVE |
| `fits` | parameter → `{stages, lower, upper, scale, by, userLocked, reason}` |
| `structure` | objective, context of use, model risk, food effect in question, measured fed solubility, planned applications (from the brief; `locked` keys a person changed, with reasons) |
| `rationale` | target → A5's explanation |
| `proposals` | A5 departures `{kind: role|fit, target, value, reason, status: PENDING|ACCEPTED|REJECTED}` |
| `acknowledged` | violation id → the person's reason |
| `layout` | canvas node positions (a view; saved with the plan as the spec asks) |
| `fit_candidates`, `budgets`, `default_rationale`, `default_limitations` | the MS-01 default, kept for the diff and the MAP |

**Locking.** A person's placement or fit is `userLocked: true`. `plan.rebase` (new inputs, a structure change) moves
every unlocked placement to the new default and keeps locked ones; an A5 proposal on a locked target is refused by code
before it reaches the diff; `:unlock` gives a study back to the default.

## 3. Routes

| Route | Does |
|---|---|
| `GET /projects/{id}/plan` | creates the plan from the accepted P4 inputs on first read (409 until P4 is accepted); returns plan, violations, `blocking`, diff, Overall Data, D1, D2, MAP state |
| `GET /projects/{id}/plan:view` | the same, read-only, for viewers |
| `PUT /plan/placements/{study}` `{role, reason}` · `?dry_run=true` | a drop on D3; dry run returns the validator's answer without saving (the canvas shows it before the person confirms) |
| `POST /plan/placements/{study}:unlock` | back to the MS-01 default |
| `PUT /plan/fits/{param}` · `POST /plan/fits/{param}:remove` | free / fix a parameter (D1, D2) with the reason |
| `PUT /plan/structure` `{key, value, reason}` | a structure choice; unlocked placements follow the new default |
| `POST /plan/violations/{id}:acknowledge` `{reason}` | a warning accepted as a limitation |
| `POST /plan/proposals/{id}:decide` `{accept, reason}` | the person's decision on an A5 proposal (accepted ⇒ placed by the person, locked) |
| `PUT /plan/layout` · `POST /plan:rebase` · `POST /plan:draft` (A5, background) | layout, new inputs, agent |
| `POST /plan:sign` `{note}` | role `modeler-reviewer` (the MIDD lead, D-07); 409 while any violation is open; MAP from the plan → `ensure_step_up` → `sign_after_step_up` (meaning Approved, bound to the MAP's content hash) → campaign inputs staged under the read root (as `campaign:prepare`) → MAP/main committed; plan and MAP approved with the signature id (P5 gate) |

After the signature every change (placement, fit, structure, acknowledgement, A5 decision, rebase on new inputs; not
the layout) is a **MAP deviation** (D-14, ICH M15 §4.2): it is saved on the plan as `deviations[]` (kind, target, what
changed, reason, by, the signed MAP version it departs from) and does nothing to campaigns until the MIDD lead signs it.
`POST /plan:sign` then generates the MAP from the plan as a **new version that supersedes the signed one**
(`supersedes_sha256`), states each deviation in its split rationale and limitations, signs it (record type
`map-deviation`, step-up), restages the campaign inputs and marks the deviations with the signature and the MAP version.
While a deviation is pending the canvas shows it and offers no "Run". Signing again with nothing changed is refused.
P6 starts with the existing `POST /projects/{id}/campaigns` using the staged inputs (the page's "Run the campaign").

**Blinding (D-15, ICH M15 §4.1).** Per project: the MIDD lead's choice with its reason (`PUT /projects/{id}/blinding`,
on the audit chain), else on by default when the human-confirmed model risk is high. While it is on and no MAP is
signed, the values of every external study (placed in S5 / S6, or entered for external validation) are left out of the
evidence page, the dataset artifacts and their history, and the study catalog; metadata and sampling times stay, since
the split is decided on them. A curator who must check one (digitization, acceptance) reveals it with a reason
(`POST /datasets/{id}:reveal`, audited). The signature lifts it. The plan page shows the state and the switch.

## 4. The live validator (`plan.validate`)

Errors block the signature; warnings block until acknowledged with a reason (then they are MAP limitations).

| Rule | Severity | Source |
|---|---|---|
| a DDI / PGx / special-population / preclinical study trains S1–S3 | error | MS-01 §3.3 rule 4 |
| a study placed on a training stage other than the one its class trains (IV → S1, fasted oral → S2, fed / IR tablet with a solution study → S3), or a class that trains nothing (MD, MR, other) | error | MAP `training_stages` |
| a fed study trains S3 while food effect is the question | error | rule 5 |
| a study without a profile (NCA or individual data only) trains a fit | error | §11.4 |
| a core study in S6, or a flagged study in S5 | error | rule 4 |
| a manual move without a reason | error | §11.4 |
| IV studies exist but none trains S1; fasted oral studies exist but none trains absorption | warning | rule 1, decision tree §6.1 / §6.2 |
| a category (fasted oral, fed, MD) with ≥ 2 studies has no judged external study | warning | rule 3 |
| an S5 study without a profile (not judged) | warning | — |
| synthetic / illustrative / unrecorded data placed outside supportive, in a non-exploratory project | warning | §9.4 (the S4/S5 signature will refuse it) |
| a fit outside S1–S3, start value outside bounds, log scale with lower ≤ 0 | error | MS-01 §4 |
| a fit at a stage where MS-01 does not list it; a fit at a stage no study trains | warning | stage plan |

## 5. The page (`/projects/[id]/plan`, `components/plan/*`, `lib/plan.ts`)

* **Overall Data** (sticky side panel): datasets (draggable chips: origin, lock, new, NCA-only, red / amber when a
  rule is broken), dissolution profiles, CPF v1.
* **D3** (`D3Dag`): stage nodes S1 · S2 · S3 on the training layer, S4 (derived: every training study), S5, S6,
  Supportive; arrows carry the CPF. HTML5 drag and drop: onto a node, onto the arrow leading into a stage (= that
  stage), or onto the training layer (= the stage the study's class trains). Each drop asks the server (dry run), shows
  the answer, then asks for the reason. Node headers drag to re-lay out the graph (saved in `layout`).
* **D1 / D2** (`Diagrams`): read-mostly (D-13). D1: plasma → binding → distribution → each placed pathway with its
  parameters; D2: solubility / permeability → products and release lanes with their oral studies → dissolution
  profiles; food-effect handling switchable with a reason. Each numeric parameter has a fit form.
* **Validator**, **changes from the MS-01 default** (applied changes and A5's pending proposals with accept / reject),
  **Approve and Sign** (disabled until the validator is green, the plan current and not yet signed), **Run the
  campaign (P6)**.

## 6. Departures from plan §11.4, and why

| Plan | Built | Why |
|---|---|---|
| React Flow + dagre | plain React, absolutely positioned nodes, SVG edges, native HTML5 drag and drop | the DAG's shape is fixed by MS-01 (seven stage nodes); native DnD is what the owner's spec asked for; no new dependency |
| new data after the plan appears *unassigned* | placed by the default and marked **new** | every study then has a role the MAP can use; the mark keeps it visible for the person |
| drop on an edge | the edge's target stage | an edge carries the CPF, not data; a drop on the arrow into a stage is read as "into that stage" |
| blinding external values until signed (D-15) | built in the API: every view that carries observed values withholds them for external studies; a curator reveals one dataset for a check, audited | source documents (the papers, the client's files) stay readable: blinding covers what the platform shows |

## 7. Known gaps

* A5 has run only with a scripted model in tests; a live run needs `MODELER_LLM_PROVIDER` on the server.
* SJ (joint refinement) and the feedback cycles (Lane B, T-51 → T-55) add stages to D3 when they land.
* Blinding (D-15) does not reach the source documents themselves (a published paper, the client's raw file).
