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
- Within this plan, slice 1 as built (after its review, 2026-11-14): the status line counts what slice 1 has, not the one
  work model: Missing and To decide from the /inputs to-do (by kind), To confirm from the client review, and the
  Delivery review's open work (table layouts to check, values with no study) said beside them, opening Client files.
  "Next" takes the delivery's layouts, then its values with no study, while a study or product still confirms on the
  delivery; otherwise the first to-do item; with nothing open, Review & sign. Slice 2 re-sources every count from
  `lib/inputsWork.ts`. Rule 4 holds for the files table only: each row opens on the file's sheets (no second list of
  cards), but until slice 2 (one file status) the Delivery review keeps its own "What arrived" list and the reading tray
  its "Show each file" list, both inside Client files.
- Within this plan, slice 2 as built (2026-11-14):
  - **URL state** is written with `window.history.replaceState`, which Next's router follows (`useSearchParams`), not
    `router.replace` (the lead's brief named it): the page is the same, so no server render is asked for at each change
    of area or filter, and a late answer cannot put back an area the person already left. Replaced, never pushed; no
    scroll jump; a link with `?tab=…&only=1&status=…` opens the page as it was.
  - **Sheet-form disagreements in To do** are settled there too, behind "Settle here", with the card's own `IssueCard`
    bound to the same server state (design rule 2; the lead's brief for slice 2), where §2.1 makes disagreements
    navigation rows. The delivery's conflicts and link questions, a study's facts and every confirmation stay on their
    cards only.
  - **The prefix alias is asked on its file's row**: "Same study as 230-23? 230-23-REF · 230-23 Fasting Reference.xlsx"
    takes the place of that file's "Link the 79 values" row (one decision, asked once), opening the delivery's link form
    for the file. "Yes pre-fills the Link row" comes with slice 4's Link table.
  - **Until slice 3**, a card confirmed on the delivery still opens in Client files (the delivery's list of studies and
    products, now with one honest standing per row); a layout row opens the delivery's list of layouts (the queue dialog
    is slice 4's); "Ask the client" lists the delivery's request with the download, without "Mark as asked" / "I have
    them…" (the disposition stays on the subject's card).
  - **Not counted in the status words:** "Ask the client" and the model checks (the design's status line counts 6
    Missing on exampleamide, without the request lines), the clean-up of a delivery whose subjects are all confirmed
    with the sheet form ("Blocks nothing"), and what a person cannot act on yet (blinded; a layout being read again).
    The /inputs to-do's "Observed data to judge on" is folded into the cards to confirm while any study waits for
    confirmation, and the software build ("check") into the model checks.
  - **The Client files badge** counts the files' open work, like every other badge; the number of files is in the
    area's head and the status line.
  - **The join uses only §2.1's two rules** (`legacy_groups`, the exact normalised label), not the design's shared-file
    and same-sheet rules: the four dissolution sheets whose product is not stated stay sheet items ("not stated: the
    product") on Products and dissolution, where 12 cards remain on exampleamide.
  - **Groups** show five rows before "Show n more" (the design's three), the first group all of them.
- Within this plan, slice 2 after its review (2026-11-14):
  - **A card signed on the delivery is counted with what holds it on its card**, read from the card itself
    (`/delivery/subjects/{type}/{subject}`, read once the page is idle, two at a time, under the key the open card uses;
    no API change): its facts not stated on one row (a gap and the check that names the same fact once), each required
    item no one settled (Missing), each failed check, disagreement, link between files or other reason (To decide). The
    spot check is the signature's first step, said on the card's confirm row, not counted apart. They are navigation
    rows that open the card (§2.1); this replaces the slice-2 note that a study's facts "stay on their cards only".
    Until a card is read, its row says it is being checked and the status line says "checking n cards…".
  - **Counted in the area the card belongs to** (Clinical studies, Products and dissolution), with a line under the
    area's head naming those cards and what is open on each, opening them in Client files until slice 3 moves them. The
    alias question ("Same study as 230-23?") is counted in Client files, where its file's values are linked.
  - **Both confirm paths stay open** (§2.2.1, ahead of slice 3's ConfirmPath): a sheet-form card of a study also signed
    on the delivery keeps its Confirm and says "Whichever is confirmed first is what loads; nothing is loaded twice"; its
    open items are counted too, and a card confirmed either way is Done.
  - **The clean-up that holds up no signature now says why, per case:** only blinded studies wait (it stays in its group,
    not counted: it counts once the plan is signed); every subject it held up is confirmed ("Blocks nothing"); its
    subjects are all confirmed with the sheet form ("Blocks nothing"). The delivery's own list of layouts shows the same:
    amber "To decide" only where a layout holds up a signature, else neutral with the reason.
  - **Words not changed here, left to the parallel ux-fill branch (commit d641c78 and its review fixes), which rewrites
    the same lines:** the raw locators in a file's table of tables and texts and in its loose numbers (`r.where`,
    `o.where`), "Not data…" and "set aside" there, and the whole of `Unassigned` ("Study not stated · to assign", "Assign",
    "regions" in its lede). The rest of `FileItem`'s words are changed here, on lines that branch does not touch.

- Within this plan, the fill round as built (slice 5 a, b and d with API 1, 2, 4 and 6, frontend only; after its review,
  2026-11-14):
  - Arms, batches and analytes are stated in the per-file link form ("Values not linked to a study or product"), not
    yet in slice 4's Link table; a link is changed only by linking again through the API (no "link elsewhere" on a
    card until slice 3 rewrites it).
  - Who made a "not data" decision and when is read from the project's audit trail (`GET /audit`, its last 2,000
    events, only while such a decision is on screen), not from the page.
  - A note outside the tables that no longer counts is a person's "not data" decision, with "Restore…", when it sits
    beside no table or beside one no layout reads; beside a table that is read, the page cannot tell a person's
    decision from the table's layout reading the note, so it says only "beside a table that is read" and offers no
    "Restore…" there.
  - "Read this table…" shows no cells: the form numbers the columns from the sheet range, and asks how many for a PDF
    or Word table. The layout words come only with a mapping, so in a project where no table has a layout yet the
    layout is written as text.
  - Compound rows to fill are offered only in a form their value can take: a value with its unit as the source states
    it; the binding partner chosen from PK-Sim's names as the API's compound spec gives them; a neutral compound as a
    statement (`phys.pka.neutral` set to 1, as the CPF records it for a published model). The solubility-vs-pH table,
    the calculation methods and the alternative rules are not offered here (named once inside the fold).
  - API follow-ups: a decision `{id, by, at, why}` on `DeliveryRegion`; who marked a note as not data and why on
    `DeliveryOutside`; the table's header cells (masked when blinded) on `DeliveryRegion`, or its region on
    `GET /delivery/source`; the layout vocabulary without a mapping; a pH-solubility table entry; and `POST /evidence`
    checking a word value against its vocabulary (it keeps "albumin" for `bind.partner` and shows it "in the model",
    which the model builder then refuses: the page now offers only PK-Sim's names).

- Within this plan, slice 4 as built (batch work, focus and speed; frontend only, 2026-11-14):
  - **Homes.** A table layout, a file's values to link and its numbers not read are settled in To do's batch tables:
    their work items open To do's row (`where` is To do; they still count in Client files, so no count changed). The
    Delivery section's own "Table layouts to check" and "Values not linked" lists are gone (one home per decision,
    §2.1); Client files keeps the per-file view (each table's "Not data…", "Restore…", "Read this table…", the layout
    chip, the per-note forms) and says that the rest is in To do. Its list of studies and products stays for slice 3.
  - **One destination in the bulk bar** is "All to one place" (study and arm, or product and batch, and the analyte, for
    every picked file); by default each picked file goes where its row says (its suggestion, its alias answer or its
    editor), so two files of one study can be given two arms in one batch. Either way one `values:assign` per
    destination; a study, arm, product, batch or analyte named new by an earlier call of the batch is then used by its id.
  - **Suggestions** fill only existing studies and products (named whole in the file's tables' titles, the lines read
    with them, or its name) and arms (an arm of the study the title names; else the words that set the file's name
    apart from the other files of the same study; else the sheet form's name past the study's), never a new study,
    except that "No" to "Same study as 230-23?" fills a new study under the sheet form's own name. A blinded file's
    titles are withheld by the API, so only its name is read.
  - **The collision guard** compares the subject and period labels of individual values going to one study in one arm
    (no arm counts as one) with one analyte; it also checks what the study already holds in that arm when its card is in
    the page's cache (it is not read for the check), and refuses before anything is sent, offering an arm each.
  - **Numbers not read:** per-cell "not data" (API 3) waits for the owner; tables with numbers no column picks up offer
    "Check its layout" (marking a whole read table as not data stays in the file's own view). What is marked in To do is
    listed under the table with "Restore…" for the visit, since a file's row leaves the list once nothing is left.
  - **Missing compound values:** a missing row of /inputs carries no unit, so the unit is typed as the source states
    it, as in the row's own form (pre-filled only where the API gives one); the web supplies no unit. The names are the
    rows' ids in words (`lib/words.ts`). A pKa and an elimination value are then settled under "Settle disagreements".
  - **Not-data layouts approved together:** offered whenever one or more layouts read a table as not data; each
    approval's note is the person's note followed by "approved with N other layouts that read a table as not data"
    (nothing added when there is only one, as on both seed projects). "Kept, not used by the model" is said only of
    excretion layouts (the intake check EXCRETION_NOT_LANDED says so); product attributes and occasions are not tagged.
  - **Reason:** the kit's `ReasonForm` is `Why` (components/delivery/shared.tsx), so every decision form on Inputs has
    the chips and "use last" (kept per project and kind of decision in the tab's session storage; the kind is the
    button's word unless a form names it). The button stays enabled except where a form's own fields disable it (the
    layout form); pressed with the reason missing it says "Give the reason: it is kept on the audit trail."
  - **Cache writes:** the cards of subjects whose own row a decision changed are read again; the others are marked stale
    and read when next shown, so a card open in Client files keeps its delivery-wide blockers (loose numbers) as they
    were until it is shown again (slice 3's gate line reads them from the page). The step bar is redrawn only after the
    compound values are entered (it follows the readiness), not after a delivery decision.
  - **A delivery whose files name no study yet:** its clean-up stays under "Blocks nothing" as slice 2 counts it; the
    reason now says so ("Its files name no study or product yet …") instead of "confirmed with the sheet form".
  - Not in this slice: the review bar (‹ Previous · Next › over the cards, with slice 3's cards), paging of a file's
    values (the first six, then all), per-cell "not data" (API 3).
