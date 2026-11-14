# Inputs, task-first: one list of work, one card per study, one row per file (plan, 2026-11-14)

**Status:** active. Owner's ask, 2026-11-14, after using the merged intake line: the Inputs page is cluttered,
unorganized, repetitive, uncategorized, unclear and unpleasant; "before I approve your work I need to actually use it, so
I must be able to fill what all is not there and make available all data for downstream tasks … most importantly work
on the frontend, UI/UX."

Evidence: `docs/plans/2026-11-14-inputs-ux-audit.md` (97 findings: 15 blockers, 54 majors, 28 minors, five lenses, two
seeded projects). Design: three competing redesigns were judged by two judges (owner lens, engineer lens); both chose
**task-first**. Its full text is in `docs/plans/2026-11-14-inputs-task-first-design.md`. This file governs where they
differ: it records the grafts from the runners-up and the lead's decisions.

## 1. What is wrong, in one paragraph
On the 9-file project the Delivery review (5,542 px) sits above the tab bar on every tab, so the five input areas start
about 6,100 px down. Two review systems show the same studies under different names with contradictory chips ("to
review" · "confirmed on its own card" · "loaded from its own card" while nothing is confirmed). Each file is listed in
5–6 places with contradictory states; four "what is missing" lists disagree; the counters ignore the Delivery pipeline.
366 values with no study need 10 separate assign forms with a reason each; 45 template header cells need 45 forms. The
reviewer reads engine words ("silent loss", "regions", "values in the ledger", `s:'Sheet1'!A4:M12`). The step bar
floats over content; native selects sit beside styled ones; amber means a dozen things. And a person cannot fill what
is missing: no arm, batch or analyte can be created, an unread table can never get a first layout, silent cells cannot
be set aside one by one, and a compound parameter that is not an S0 to-do has no row to fill.

## 2. The design (task-first, with grafts)
Six rules (design text §Principle), unchanged:
1. **One list of work.** `lib/inputsWork.ts` builds every count on the page from both pipelines, the /inputs to-do list
   and readiness: the status line, the tab badges, each card's blockers, each file's "still needs you".
2. **One home per decision.** A decision has one component and one place to act.
3. **One card per study or product, one confirm path per card**, chosen by `confirm_on`; the other reader's view is
   folded into the card as read-only "How the files were read".
4. **One row per file**, in the Client files tab. No other file list.
5. **Four status words:** Missing · To confirm · To decide · Done. Amber only where the person must decide.
6. **Nothing a person can do today becomes impossible.**

Page: compact head ("Fill in what the model needs and confirm the client's data.") with an Add data menu; static step
bar; one status line with the single primary "Next" button; a sticky area bar **To do · Compound · Products and
dissolution · Clinical studies · Populations and individuals · Simulation settings · Client files**. The page opens on
To do while anything is open.

### 2.1 Grafts from the runners-up (both judges agreed)
- **One home per decision (study-first).** In To do, act inline only on file-level and batch work (table layouts, link
  values, numbers not read, ask the client, the S0 batch). Subject-level facts, disagreements, link questions and
  confirmations are navigation rows that open the card; they never render a second form. Each area gets a one-line head
  ("9 studies · 4 to confirm · 3 to decide · 2 files not linked") instead of an "Open here" strip.
- **Conservative join (study-first).** Merge a Delivery subject and a sheet-form group only on a `loaded_elsewhere`
  dataset id or an exact normalised label. A prefix alias (230-23-REF / 230-23-TEST beside 230-23) becomes a To decide
  question "Same study as 230-23?"; Yes pre-fills the Link row with that study and the suggested arm. No silent merge.
- **Study card anatomy (study-first):** To do on this study · Facts (typed; the sheet reader's answers as suggestion
  chips) · Observed data · Files and tables · Checks · Not loaded with this study · one Confirm · How the files were read.
- **"Only what needs me" filter** on every area and on Client files.
- **Loaded / available downstream (guided).** The Done group and each confirmed card say who signed and when, what
  loaded (datasets, values, dissolution records), where it now lives, what was held back, and "Changed since signed:
  confirm again". The status line says "In the model: n studies · n formulations · n compound values".
- **Fewer refetches (guided).** A decision's response (values:assign and regions:exclude already return the page) is
  written into the query cache; a decision click costs at most 2 requests.
- **Layout rows (guided)** expand to one-line column summaries ("time ← 'Time (h)' · concentration ← 'Conc (ng/mL)'").
  Per-layout review stays the default; bulk approval only for "not data" readings, each note saying "approved with N
  other layouts".
- **URL state:** the area and the To do filter live in the URL.
- **Context labels** on repeated buttons ("Link the 76 values of 230-23 Fasting Reference.xlsx").
- Skip link to the areas; studies sharing one individual sit on one line.

### 2.2 The lead's decisions on what the judges found missing from all three
1. **A working path while the delivery-wide gate holds.** A Delivery-path card that also has a sheet-form group shows
   both paths in the card, never in a ⋯ menu: while the gate holds, "Confirm and sign" is disabled with the gate line
   and "Confirm now with the sheet form" is offered beside it with the warning "Whichever is confirmed first is what
   loads". The owner decides later whether the gate becomes per subject (contracts §11.10); the UI does not change it.
2. **Arms before bulk linking.** The Link table refuses to link two files whose labels collide (same subject and period)
   to one study without distinct arms; `new_arm` (API 2) ships with or before the Link table.
3. **Server-side join.** `DeliverySubjectRow` gains `legacy_groups` (the client-review group ids of the same source,
   from the overlap the API already computes), so the join does not depend on fetching every card.
4. **Undo.** "Mark as not data" gets "Restore…" with a reason (API 6); a link is changed by linking again (an
   assignment replaces the earlier one whole). The study card lists the decisions made on it (who, when, why) before
   "Confirm and sign", so the signer sees what was linked, excluded, approved or overridden.
5. **Blinded subjects:** Next and the counts skip items a person cannot act on while blinded; their rows say why.
6. **Concurrent reviewers:** a 409 on a decision already made shows the server's words and refreshes that item.
7. **An end-to-end test of the owner's job** on its own seed: files uploaded → layouts checked → values linked (arms) →
   facts filled → signed → visible "In the model".
8. **Categorized studies:** the Clinical studies list groups by design where the facts allow (IV · oral fasted · oral
   fed · multiple dose · other), the owner's "uncategorized".

## 3. API changes (all additive, unlocked files; OpenAPI + api-types + CHANGELOG each)
| # | Change | Why | Status |
|---|---|---|---|
| 1 | GET /inputs: an `empty` row for every model-placed registry parameter the data plan owns | a parameter that is not an S0 to-do has no row to fill | build |
| 2 | values:assign gains `new_arm`, `new_batch`, `new_analyte`, `analyte`; `study_options` gains `analyte` and `matrix` (harvested vocabularies) | Test and Reference of 230-23 collide; CL-01's analyte and matrix cannot be stated | build |
| 3 | `silent_cells` on a region (capped, withheld when blinded) and exclusion scope `cells` | 72 silent cells block every signature; the only remedy is discarding a table | **owner review**: changes what counts as excluded for G2 (a person's reasoned decision per cell, as today per region) |
| 4 | POST /delivery/mappings:propose; the mapping `vocabulary` | an unread or rejected table can never get a first layout; corrections are raw JSON | build |
| 5 | person-entered demographics (`:enter`) count as found | "Enter them…" must clear the requirement | check, fix if needed (no ruleset change) |
| 6 | regions:restore (with a reason) | undo for "Mark as not data" | build |
| 7 | `DeliverySubjectRow.legacy_groups` | server-side join (§2.2.3) | build |

Not changed (owner or SME decisions): the per-delivery gate (§11.10); template header cells counted as loose numbers
(`intake_rules.yaml`, SME, UNVERIFIED); layouts of data that never lands still needing approval; retiring a pipeline.

## 4. Slices
Each slice keeps `make test`, `make lint`, `npm --prefix apps/web run typecheck` and `build` green, updates the e2e
specs whose elements it moves (testids kept wherever the element survives), adds its CHANGELOG entry, and is reviewed
before the next starts.
1. **Frame** (frontend + CSS): head, static stepper, status line, sticky area bar with To do and Client files; the
   Delivery review and the AI reading line move into Client files; the files drawer and per-area file bars go; the CSS
   fixes (`.brand` scope, dead band, base control style, contrast tokens, reveal opt-out, `elim` regex).
2. **One list and one vocabulary** (frontend; API 7): `lib/inputsWork.ts`, `lib/words.ts`, the To do tab, counts from
   one model, one file status, honest chips.
3. **One card per study and product** (frontend): StudyCard, ProductCard, ConfirmPath (§2.2.1), DeliveryReview with
   the gate line and the decision list, FactsForm, categorized study list, Loaded / In the model, empty states, charts.
4. **Batch work, focus and speed** (frontend; API 2 and 6): LinkTable with arms, NotReadTable, MissingValues,
   LayoutQueue, Reason with suggestions, BulkBar, focus and live region, cache writes, phone layout.
5. **Fill what is missing** (API 1, 3 after the owner's review, 4, 5): registry rows on Compound, per-cell not data,
   the structured layout editor and "Read this table…", demographics.

## 5. Deviations recorded
- From `docs/plans/2026-11-12-intake-contracts.md` §8.10 ("one slot beside ReadingTray"): the Delivery review leaves the
  page top; its file-level parts go to Client files and To do, its subject parts to the cards.
- From `docs/plans/2026-11-03-inputs-and-client-data.md` §3.2 (left rail; "To confirm" at the top of the rail; a files
  drawer): a sticky horizontal area bar (the 2026-11-06 segmented-control decision), To do as the first area, Client
  files as the last. §3.2's principle that client data lands in its home area is kept by the cards.
