# Bloatware Report (Phase 2, identification only)

> **Gate 2 update:** every candidate now has a verified verdict in [`REMEDIATION_PLAN.md`](REMEDIATION_PLAN.md) §3, which supersedes the recommendations below where they differ.

**Nothing has been removed.** Each candidate needs verification and the owner's authorisation (Phase 9/10). Locked
files are marked; they change only in their own PR with the owner's approval.

Confidence: **High** = proven by search or test; **Medium** = strong evidence, one path unchecked; **Low** = smell.

## Summary

| ID | Candidate | Class | Confidence | Recommended action |
|---|---|---|---|---|
| B-01 | Two parallel intake UIs (Inputs task-first vs Data room) | duplicate workflow | High | Owner decision; then retire one path in the UI |
| B-02 | 22 API operations with no UI caller (Gate 2 correction) | unused routes | High (no caller) / Medium (no other consumer) | Keep, expose, or deprecate each (table below) |
| B-03 | `escalation:decide` beside `escalation:resolve` | duplicate route | Medium | Confirm no client; deprecate in OpenAPI |
| B-04 | `/review` page that only redirects | obsolete route | High | Keep the redirect until bookmarks age out; no action |
| B-05 | `components/ui.tsx` beside `components/kit` | duplicate primitives | High | Merge into one kit in the redesign |
| B-06 | 46 files with raw `<table>` vs `kit/SortableTable` (10) and `kit/DataTable` | inconsistent tables | High | One table component in the design system |
| B-07 | 20 CSS files in a fixed cascade; `design.css`, `targets.css`, `utilities.css` override earlier sheets | style debt | High | Replaced by the new design system; delete after migration |
| B-08 | 39 inline `style={{}}` uses | style debt | High | Tokens / utilities |
| B-09 | Motion system (spring, magnetic tiles, parallax, celebration burst, rolling counters) | decoration | High | Drop for a console; keep reduced-motion respect |
| B-10 | Decorative hero with curve on every page | decoration | High | Replace with a compact page header |
| B-11 | `lib/words.ts` (1,266 lines) and `lib/inputsWork.ts` (1,598 lines) | large modules | Medium | Keep (owner rules); split by area during implementation |
| B-12 | `delivery_routes.py` (2,085 lines), `DeliveryReview.tsx` (1,062), `InputsWorkspace.tsx` (922) | large modules | High | Split during implementation, no behaviour change |
| B-13 | Library modules with no production importer | dead / tooling code | Medium | Classify per row below |
| B-14 | Dashboard `/steps` N+1 | performance | High | Add step state to `GET /projects` (backend change) |
| B-15 | 30 s escalation polling from every page | performance | High | SSE or a single status endpoint |
| B-16 | `modeler-qa` role with no permissions | dead config | High | Define QA's permissions or stop offering the role |
| B-17 | Stale docs | doc debt | High | Update README "web front end starters", `lib/writes.ts:39` comment |
| B-18 | Clone is shallow; history before 2026-11-11 only in CHANGELOG | tooling | High | No action; note for audits |

## Detail

### B-01 Two intake paths
- Evidence: `/projects/{id}/inputs` (task-first, 2026-11-14 → 19) and `/projects/{id}/dataroom` (2026-11-21 → 22);
  the Data room footer links "The earlier Inputs page" and Inputs links "Open in the Data room"
  (`current-state/03-inputs-todo.png`, `04-dataroom.png`). Backend: `client_api.py` + `delivery_routes.py` (41 ops)
  vs `dataroom_api.py` (15 ops); L3 `modeler_project.delivery*`/`client_review` vs `modeler_project.dataroom`.
- Impact: two mental models, two sets of decisions, two "send to model" paths; the redesign's IA cannot settle without it.
- Action: owner decision (question Q1 in the Gate 1 summary). Do not remove backend code until the retired path's
  data is migrated or archived.

### B-02 API operations with no UI caller
| Operation | Other consumer | Recommendation |
|---|---|---|
| `GET /health` | `deploy/server/qualify.py` | Keep; show in a System status page |
| `POST /runs`, `POST /model-versions/preview`, `POST /m15/validate` | none found | Keep (engine/expert tools); expose under an Expert tools area or document as API-only |
| `GET /runs/{id}/results` | none found | Expose in the campaign's run detail |
| `GET /campaigns/{id}/package` | none found | Expose as a package browser |
| `GET /projects/{id}/agent-runs/{run_id}` | none found | Expose as agent activity |
| `GET /proposals` | none found | Deprecate or expose with a decide route |
| `GET /escalations/decision-options` | none found | Verify the UI's source of options; expose or deprecate |
| `escalation:decide`, `feedback:decide` | none found | See B-03 |
| `map:generate` | none found | Verify superseded by the plan canvas; deprecate |
| `client-review:edit` | none found | Verify superseded by `delivery/...:enter`; deprecate |
| `plan/placements/{s}:unlock` | none found | Expose on the canvas |
| `plan:view` | none found | Use for a reviewer's read-only plan |
| `projects/{id}/impact` | none found | Expose as an impact preview |
| `requirements` (3 ops) | none found | Expose as the data-plan matrix |
| `templates` (2 ops) | none found | Project starting points (reference models), not analysis templates; owner question Q2 |

### B-03 Duplicate escalation routes
`escalations.py:139` (`:decide`) and `:231` (`:resolve`); the web calls `:resolve` twice and `:decide` never (grep).
Both sign. Verify no other client (scripts, tests that represent contracts) before deprecating. **Signature-path code:
treat as Part 11 sensitive.**

### B-05 / B-06 / B-08 Duplicated UI primitives
- `components/ui.tsx`: `RiskChip`, `ProvenanceChip`, `Completeness`, `StatusChip`, `Card`, `ApiProblem` (28 importers).
- `components/kit/index.tsx`: `Hero`, `PageShell`, `SidePanel`, `EmptyState`, `InlineIssue`, `Banner`, `DataTable`
  (43 importers), plus `kit/SortableTable`, `kit/Dialog`, `kit/Menu`, `kit/Tabs`, `kit/Stepper`.
- Dialogs: `kit/Dialog`, `kit/BulkBar`, and the plan canvas draw dialogs; `StepUpDialog`, `delivery/ConfirmDialog`,
  `campaign/EscalationPopup` wrap them (INFERRED from imports).
- No orphan component files: every file under `components/` and `lib/` is imported (VERIFIED by name search).

### B-07 Style debt
2,898 CSS lines across 20 files loaded in a fixed order in `app/layout.tsx`; comments state later sheets exist to win
the cascade ("loaded last, so it wins"). Tokens live in `globals.css` (65 custom properties) with aliases kept for
older names (`--brand`, `--accent`, `--text`, `--border`, `--surface-2`). Replacing the visual language replaces most
of this; keep `targets.css` rules (WCAG 2.2 target size) as requirements, not as code.

### B-13 Modules with no production importer (Python)
Found by a scripted import scan, then a text search for each name outside tests.

| Module | Lines | Assessment |
|---|---|---|
| `modeler_project.value_score`, `value_key`, `key_compare`, `arrival_eval`, `format_inventory`, `intake_fixtures` | 1,396 / 720 / 283 / 304 / 134 / 440 | Evaluation and test tooling (scoring deliveries against analysts' keys). Keep; consider moving under an `evals` package |
| `modeler_agents.evals.*`, `modeler_agents.llm_check` | 323 + 62 + 78 | Eval harness and CLI. Keep |
| `modeler_orchestrator.worker`, `modeler_engine.worker`, `modeler_orchestrator.workflows` | 41 / 69 / 100 | Temporal entry points for the distributed path (built, not deployed). Keep |
| `modeler_engine.objectstore` | 63 | S3/MinIO path for the distributed deployment. Keep |
| `pbpk_domain.ddi_static` | 120 | DDI static screening; no API. **Expose** (class 3), not bloat |
| `pbpk_domain.snapshot.parameter_transfer` | 50 | No consumer found outside tests; CONTINUATION D3 says transfer updates the CPF instead. Medium: verify, then remove |
| `modeler_agents.literature`, `modeler_agents.parameter_curation` | 244 / 237 | Only tests import them. Medium: verify superseded by `evidence:research`, then remove or wire |
| `modeler_intake.pksim` | 185 | Used by `services/engine-worker/golden/make_example_snapshot.py` (locked golden). Keep |
| `pbpk_domain.requirement_drafts` | 22 | **Keep**: inert by the owner's decision (drafts await a named scientist). Verified at Gate 2 |

### B-14 / B-15 Performance
- Dashboard: one `GET /projects/{id}/steps` per project (app-design-merge plan §4 gap 3).
- `Nav.tsx` `useApiLive` polls `/api/v1/escalations` every 30 s on every page, and `EscalationPopup` polls the same
  read; one shared query (TanStack cache key) INFERRED to dedupe them.

### Dependencies
All four runtime dependencies are used: `next`, `react`/`react-dom`, `@tanstack/react-query` (19 files),
`plotly.js-dist-min` (2 files), `pdfjs-dist` (2 files). Plotly's minified bundle is large (INFERRED ~3.5 MB); a lighter
chart library is a design-system decision, not bloat. Python dependency audit: not done (UNKNOWN.md U-07).
