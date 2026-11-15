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

- Within this plan, slice 3 as built (2026-11-14; frontend only):
  - **Where the new parts live:** `FactsForm` (with the demographics form) and the decision list (`Decisions`) are in
    `components/delivery/`, beside `DeliveryReview`, since both post to or read a delivery subject; the cards
    (`StudyCard`, `ProductCard`, `CompoundCard`, `ConfirmPath`, `HowRead`, the card's To do) are in
    `components/inputs/cards/`. The sheet form's draft needs stay in `DraftItem` (not merged into `FactsForm`).
  - **"Confirm now with the sheet form"** opens the sheet form's view on the card in its confirm form (its facts, its
    disagreements, its own "Confirm"); it does not confirm in one click. It is offered whenever the card has a sheet-form
    group still to confirm, as "Confirm with the sheet form instead" while the clean-up does not hold the signature,
    because the one list of work counts that group's open items on the card (slice 2, "both confirm paths stay open").
  - **"Confirm and sign" is disabled** while the card's own blockers include the clean-up's codes (SILENT_LOSS,
    OUTSIDE_NUMBERS, UNASSIGNED_VALUES), read from the card; the gate line's words are the one list's (`gateText`). The
    other blockers still let the dialog open, which names them, as before.
  - **The decision list** reads who, when and why from the project's audit trail (its last 2,000 events) and what each
    decision was from the card and the delivery page: checks accepted as is (by check id), entries and corrections (by
    fact id), required items settled (by disposition id), table layouts approved or rejected (by layout id and version),
    tables of its files marked as not data (by decision id). A value not used after a choice and a refused link are listed
    with their reason only (the trail does not name the subject); values linked to the study from a file that did not name
    it are not listed (the trail does not say which study a link went to). API follow-up: a subject's decisions
    `{kind, what, by, at, why}` on its card.
  - **The demographics form** offers the population's words from a table layout's vocabulary
    (`GET /delivery/mappings/{id}`: the intake vocabulary is only there), typed when the project has no layout; the
    other fields are numbers under the intake rules' names for REQ-sys.demographics. Whether person-entered demographics
    count as found is API change 5 (slice 5 e), not checked here.
  - **The Clinical studies list** is grouped by the facts known without new reads beyond the cards: the study in the
    model, the sheet form's facts, and the delivery card's facts (read for the studies confirmed on the delivery and not
    yet confirmed, two at a time, under the key the card uses, when the area opens). An oral study whose food state no
    file states is under "Other or not stated yet". The list is one kit `DataTable` (which gains a row testid, a row's
    detail under it and group heading rows), not one table per design: a study whose facts move it to another design (its
    route entered) stays the same row, so its open card, and a signature dialog on it, are not lost.
  - **Not in the design, added:** a table of values on a card is one line until opened, open by itself when a row of it
    needs the person (the 230-23 card was over 6,000 px with every table open); a card's facts are listed once each and
    without the subject's own id; the rows of a study's table no longer repeat "study 230-23". Up to three cards in an
    area are all open; past three, the first to confirm (as `ConfirmGroups` did). The Delivery section in Client files
    keeps one line naming the areas where its subjects' cards are, with links.
  - **Not built here:** "Used by 230-23, 231-24" on a product card (nothing the page reads says which studies give a
    product); "Show separately" for a joined card (the join has no wrong merges on either seed); "In the model" links for
    products and the compound (a study's link scrolls to its row); the "Nothing on this tab yet" empty-state title of
    `InputRows` (owned by the slice-4 branch). The client's compound values as a card on Compound shows only where a
    delivery or sheet-form compound subject exists.
- Within this plan, slice 3 after its review (2026-11-15; frontend only):
  - **Asked once, counted once:** on a card confirmed on the delivery, the sheet form's sheets that do not say a fact
    are no longer rows of the one list of work (they were counted beside the delivery's own facts row, which asks for the
    same facts). They are asked inside the sheet form's path when the person chooses it; the card's sheet path says how
    many things the sheet form has first. The sheet form's disagreements on such a card are still counted. This narrows
    slice 2's "both confirm paths stay open … its open items are counted too" to the disagreements.
  - **A card the sheet form confirmed first** reads as a sheet-form card (the group as its body, the delivery's reading
    folded for reference), whatever its `confirm_on`.
  - **"State it…" for ANALYTE_MISSING** links the check's values again (`values:assign`) with their study, arm, product
    and batch named again and the analyte chosen or named, one link per set of values that share those: an assignment
    replaces the earlier one whole, so naming them again is what keeps them. Not offered while the study is blinded.
  - **"Fill in…" for DISSOLUTION_METHOD_INCOMPLETE is not built.** The method a run must state is the `conditions` of
    each dissolved value of the run (`intake_checks._dissolution_method_incomplete`); the check names no values, and
    the only way to give values new conditions today is to correct each one through `:enter`, which would re-enter every
    point of the run as a person's entry and drop its file as its source. The check keeps "Accept as is…". API
    follow-up: a run's method stated once (its batch and conditions, with a reason), kept beside the values it applies to.
  - **A study's datasets on its card keep every action** of the dataset list (reveal for a check, the overlay check, the
    flags, the digitization, the reported PK; plan rule 6); the study's row says what waits among them while its card is
    closed.
  - **A card opened from To do or "Next"** lands at its head (a study's: its row) with the focus on the control that
    opens it; an item inside a card at its place, the focus on its first control.
  - **Not changed here:** the delivery API does not blind a client study that the project blinds by its id (CL-2 on
    clientamide with an external dataset filed under it): the page now withholds the delivery's reading of such a study
    in "How the files were read", but the sheet form's group shows what the client-review API sends. Whether the client
    review and the delivery should blind it is an API question for the owner.

- Within this plan, the fill round's API follow-ups as built (branch ux-api2, 2026-11-15; CHANGELOG "who marked a thing
  'not data', a table's first rows, the layout words and PK-Sim's names"): done, all but the pH-solubility table entry,
  which was not part of this branch and is still open. The notes above on the audit trail, on a note beside a table that
  is read, on "Read this table…" showing no cells and on the layout words coming only with a mapping no longer hold.
  - **The restore stays in the record** as a second field, `restored` (the latest restore that gave a region or a note
    back, with what it undid), beside `decision` (the one in force), on both `DeliveryRegion` and `DeliveryOutside`.
  - **A table's first rows are on `DeliveryRegion.head`**, not on `GET /delivery/source` by region: "Read this table…"
    needs them with no further request. They are masked by file, as a mapping's sample is (a file that holds a blinded
    study's values shows its header band only, digits masked), not by region as a value's source view is: an unread table
    holds no value yet, so the source view's rule would show it whole in a blinded study's file.
  - **The layout words are on their own route** (`GET /delivery/vocabulary`), not on `DeliveryPage`, which the page reads
    again every 3 seconds while a file is read.
  - **Blinded files, a hardening beyond the brief:** the digits of a person's "not data" why are masked, on the region's
    `reason` too (its decision's id kept), as a failed run's message is, since the new fields put that why beside a note
    whose text is withheld.
  - **PK-Sim's names** are checked on `POST /evidence` (the person's typed value). `GET /inputs` gains
    `CompoundRow.allowed` so the row's form reads the names from the API, not from a list typed in the web.
  - **`DeliverySection`'s region rows are not changed here** (another branch rewrites them): `Restore.tsx` keeps
    `useDecisionsWho` (now reading nothing) and `NotDataNote`'s `who` so they compile; only the note lines use the new
    fields, and a region's `restored` is shown once its row renders `NotDataNote` on every region.
  - **After its review** (same branch, 2026-11-15), each a deviation recorded here:
    - **PK-Sim's names on every person's route**, not only `POST /evidence`: `:correct` (in `evidence_register.correct`),
      `:decide` ACCEPTED and `:choose` refuse a binding partner that is not one of PK-Sim's names (422 `NOT_ALLOWED`),
      so a literature agent's proposal or a name corrected into bind.partner no longer reaches the model by a person.
      `:decide` and `:choose` check in the route, not in `evidence_register.decide`: a signed delivery's landing and the
      client-review card's confirmation accept through it, and a refusal there would stop a signed landing half
      written. Those two paths and values kept before stay unchecked; such a kept value is said on its Inputs row
      (`CompoundRow.message`, chip "not a PK-Sim name", how to replace it). A published model's "unspecified"
      (`cpf.build.UNSPECIFIED_PARTNER`, which the builder takes as "not set") is let through when accepted or kept, never
      when typed. Checking the landing at plan time (held, before signing) is left for later.
    - **The region rows render `NotDataNote` after all**, on every region (the decision, or else the restore, beside why
      it is not read); `useDecisionsWho` and the `who` prop are removed. `shared.personDecision` stays, because the
      integration branch's `Decisions.tsx` (slice 3) reads it; it can read `DeliveryRegion.decision` after the merge.
    - **A merged cell in a table's first rows** is said by `DeliveryRegionHead.spans` (1, n over n columns, 0 covered),
      not by blanking the covered cells: the rows keep the merged text in each column, as a mapping's header reads it,
      so the columns stay named by it; the grid draws it once.
