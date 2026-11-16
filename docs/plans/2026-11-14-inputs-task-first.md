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
    card until slice 3 rewrites it). Slices 3 and 4 did not build it; the final review's linking fixes did, on a file's
    row in Client files ("Link elsewhere…", below).
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
  - **Suggestions** fill only existing studies and products (named whole in a table's own title and the lines read with
    it, else, when no table's title names one, the file's name) and arms (an arm of the study the title names; else the
    words that set the file's name apart from the other files of the same study, those to link and those already linked
    that share a word of its name; else the sheet form's name past the study's), never a new study, except that "No" to
    "Same study as 230-23?" fills a new study under the sheet form's own name. A blinded file's titles are withheld by
    the API, so only its name is read.
  - **One row per file, split by table when its tables differ** (after the review, 2026-11-15; plan §2 rule 6: each
    table had its own link form before this slice): each table is a part of its row with the facts read on its sheet or
    page (when it is the only table there; the others' facts form a part of their own). A file whose tables' titles
    point to different places (one names a study, another another or none) starts with each table in its own place;
    "Each table to its own place" splits any file in its editor, or puts it back together. One `values:assign` per
    destination either way.
  - **The collision guard** compares the subject and period labels of individual values going to one study in one arm
    (no arm counts as one) with one analyte, a file's (or a table's) against the others' and against what the study
    already holds in that arm, never one file's tables with each other or with what the study holds of that file. What
    the study holds is its card (after the review: read by the rows while they say where they go, and read again before
    a link unless the page read it in the last 10 s; a card not read is never taken as empty, and one that cannot be read
    refuses the link). It refuses before anything is sent, offering an arm each.
  - **Numbers not read:** per-cell "not data" (API 3) waits for the owner; tables with numbers no column picks up offer
    "Check its layout" (marking a whole read table as not data stays in the file's own view; since the final review it is
    offered in To do too where the file's studies are confirmed with the sheet form). What is marked in To do is listed
    with "Restore…" for the visit, since a file's row leaves the list once nothing is left (since the final review, kept
    by To do after the table's last row goes too).
  - **Missing compound values:** a missing row of /inputs carries no unit, so the unit is typed as the source states
    it, as in the row's own form (pre-filled only where the API gives one); the web supplies no unit. The names are the
    rows' ids in words (`lib/words.ts`). A pKa is then called acidic or basic under "Settle disagreements". (Corrected
    by the final review, OWN-5: an elimination value is no longer taken for the placeholder and settled later; its
    pathway is asked first, in the table, with the unit the API names: "Final review fixes: compound, products …".)
  - **Not-data layouts approved together:** offered whenever one or more layouts read a table as not data; each
    approval's note is the person's note followed by "approved with N other layouts that read a table as not data"
    (nothing added when there is only one, as on both seed projects). "Kept, not used by the model" is said only of
    excretion layouts (the intake check EXCRETION_NOT_LANDED says so); product attributes and occasions are not tagged.
  - **Reason:** the kit's `ReasonForm` is `Why` (components/delivery/shared.tsx), so every decision form on Inputs has
    the chips and "use last" (kept per project and kind of decision in the tab's session storage; the kind is the
    button's word unless a form names it). The button stays enabled except where a form's own fields disable it (the
    layout form); pressed with the reason missing it says "Give the reason: it is kept on the audit trail."
    (Corrected by the final review round 3, INT-12, CODE-6, CODE-7: every form names its kind, the key holds the person
    signed in, sign-out forgets it, and the field is emptied once a decision is made; slice 3's card forms, which still
    disabled their buttons silently, now say what is missing too: "Final review fixes round 3: accessibility and
    forms".)
  - **Cache writes:** the cards of subjects whose own row a decision changed are read again; the others are marked stale
    and read when next shown, so a card open in Client files keeps its delivery-wide blockers (loose numbers) as they
    were until it is shown again (slice 3's gate line reads them from the page). The step bar is redrawn only after the
    compound values are entered (it follows the readiness), not after a delivery decision. (Round 3 made this true for
    every decision on Inputs, slice 3's cards included, which still read everything: "Final review fixes round 3".)
  - **A delivery whose files name no study yet** (after the review, 2026-11-15): not counted, as slice 2 counts it (it
    holds up no signature), but its layouts, values to link and numbers not read stay in their own groups in view, the
    group saying once how many are not counted and why ("Its files name no study or product yet …"), not under "Blocks
    nothing": linking those values is what brings them into the model. A file's "Still needs you" lists that work too,
    marked "not counted now". "Blocks nothing" keeps the clean-up of deliveries whose studies are all confirmed (on the
    delivery or with the sheet form).
  - **Going to an item** (Next, "Still needs you", the Delivery section's "To do") drops what would hide it: a status
    filter that is not the item's own, "Only what needs me" for an item not counted; a folded group it sits in is
    unfolded.
  - **The study card's own form for a loose number** (`SubjectCard.tsx`, `delivery-outside-accept-<n>`) is kept here:
    slice 3 replaces that card (its `DeliveryReview` settles the numbers outside the tables with their file, never on the
    card) and deletes the file, so removing the form in this slice would only make the two branches conflict. Until the
    merge the card is a third place to mark a loose number as not data, beside To do and the file's view in Client files.
  - Not in this slice: the review bar (‹ Previous · Next › over the cards, with slice 3's cards), paging of a file's
    values (the first six, then all), per-cell "not data" (API 3).

### Final review fixes: blinding, Part 11 records and the decisions list (2026-11-15; API and frontend)
- **Where the decisions come from (INT-1).** The card's API gives a subject's decisions (`DeliverySubject.decisions`,
  read from the intake's own logs by `modeler_project/intake_decisions.py`), the API follow-up slice 3 named; the
  decision list no longer reads `GET /audit`. This replaces slice 3's note that who, when and why come from the audit
  trail's last 2,000 events and that links are not listed. Masking reuses the delivery's rule: digits masked (`_mask`),
  for a blinded subject and for a decision about a file that holds a blinded study's values (`blinded_files`). `GET
  /audit` masks the reason of such intake events too while the study is blinded; the stored chain is unchanged.
- **What a signature binds, listed (gaps 6, 9; INT-8).** "Subject": its own decisions, the layouts of its own tables
  (naming every file each reads now), the values linked to it, and the "not data" decisions and restores in the files
  its values were read from. "Delivery": the layouts, links and "not data" decisions of the delivery's other files and
  tables, folded under one line. A link the subject lost to a later relink stays listed with "since linked elsewhere".
  A stale confirmation lists the decisions made after it was signed; a file read again with no person's decision is
  said as such, not named (runs carry no reason).
- **Blinding by the delivery on the sheet form (INT-2).** A client-review group is the delivery's blinded subject's when
  `legacy_groups` names it or its name is the subject's label (the join's two rules, §2.1). Its facts, options, draft
  answers and points are withheld in `GET /client-review`; `:finish`, `:confirm`, reading one of its sheets and
  `:map` on such a sheet answer 409 `BLINDED`. Sheets are found by the anchors of the blinded study's values (a sheet of
  the same workbook with another study's values stays open); a page of a PDF or Word file is masked file by file, as
  the delivery's file-level rule and the source view's rule for a text of such a file do. Not done: the `:select`,
  `:reopen` and `:edit` routes of such a group (they load nothing; the page offers none of them for it). *Corrected by
  "Final review fixes: round-1 remainders" below:* the sheet form's purpose is now checked against the delivery's
  `intended_use` (it was not moot: once the MAP is signed the refusal lifts), and a study the project's blinding list
  holds is withheld by the same rule.
- ~~Not changed, for the owner: the raw file route still serves a blinded file~~ *(round 1's note, wrong, corrected
  below):* round 1 kept `/documents/{sha}/raw` open on the grounds that refusing it would stop D-15's reveal for a check
  (digitization), and said Inputs no longer offered the link. Both were wrong: the Digitizer on the Studies area drew a
  blinded study's whole table from that route, and the reveal is `POST datasets/{id}:reveal` (a reason on the audit
  chain, the dataset's values), which never reads the file. The route now answers 409 `BLINDED` for such a file.
- **Two confirm paths, two Part 11 controls (INT-7) — open decision for the owner (contracts §11.10).** "Confirm and
  sign" records an electronic signature (step-up, meaning Reviewed, the record's sha256); "Confirm now with the sheet
  form" records who confirmed and when, with no reason, step-up or signature. The path stays (§2.2.1); its note now says
  it is not signed. Whether a study that is also a delivery subject must be signed on either path is the owner's call.
- **A second accept-as-is is refused (INT-6):** `:override` answers 409 `CONFLICT` with who, when and why when the
  check is overridden already. `values:assign` keeps no precondition: relinking is how a link is changed (§2.2.4); a
  page that did not see another person's link still links again, and both links are listed.

### Final review fixes: linking values, arms, analytes and the sheet-form join (2026-11-15; OWN-1, INT-4, OWN-11, INT-5, OWN-4, INT-9, OWN-3, INT-10, the owner-job gaps 4 and 8; CHANGELOG "Fixed — final review, linking …")
- **A link across a re-read** (`modeler_project/link_carry.py`, the pipeline's ledger stage): carried over only when
  it covered the whole earlier reading of the table (each value but those a person set aside one by one), as one
  audited `assignment` line by "code" naming the original ("carried over from as-n after a re-read: …"). A link that
  covered part of the table is not carried (which part it would cover after the re-read cannot be told): the link row
  comes back filled with its destination and says why (`DeliveryPage.relink`), and the person links it again. Nothing
  is carried into a reading that names a study or product itself, nor from a reading a person marked as not data. A
  link carried is the person's: the arm check is not run on it again. Links lost before this change come back the
  same way (pre-filled, "read again before links were carried over"). Checked by the API (a link survives a corrected
  and approved layout; a partial one comes back) and by the work model's unit checks (the row filled and its words);
  no browser flow corrects a layout after linking (the owner job approves its layout first, as To do orders it).
- **The arm guard** is the API's too (409 on values:assign). For "as the file says" the API compares the analyte the
  values carry now (after any earlier link), the web the file's own; both match any analyte when none is stated.
  *Corrected by "Final review fixes: round-1 remainders":* round 1's rule (subject, period, analyte) refused a urine and
  a plasma file of one study and the card's "State it…"; it now compares the ledger's conflict key and leaves values that
  stay where they are alone.
- **Analytes stay one entity per file** (the ledger resolves an analyte inside its file and compares a study's by
  name, `ledger_view._entity_key`): not a ledger change. The pickers offer one per name, the one the study uses.
- **"Link elsewhere…"** is on a file's row in Client files, ~~per link in force on its values~~ (per place its values
  went to since the round-1 remainders: below), not on a card's Files and tables (one home per decision); not offered
  for a blinded file (its values are withheld until the plan is signed). A link elsewhere replaces the earlier one
  whole, with the arm, batch and analyte chosen in the form.
- **The join by linked file:** `legacy_groups` names a client-review group when every one of its items was read from
  files a person linked on the delivery whose values all belong to that one subject (no value left with no subject);
  a file that names its study itself joins by the exact label as before. A joined card keeps the key of its own name.
  **Not built here:** the sheet form's path on a joined card ("Confirm now with the sheet form") pre-filled from the
  facts entered on the delivery card (the sheet form's offers, `study_offers`, do not read the delivery's person
  entries, and the sheet form names the study otherwise, 230-23-REF). Built since in the page, with no API change
  (below, "Final review fixes: cards, counts, demographics and repetition").
- **`loaded_elsewhere`** now means accepted (in the model); `proposed_elsewhere` lists the datasets of the same source
  only read with the sheet form. The join reads both.
- **A disagreement's subject:** the card's To do lists a subject's disagreements under one line ("Subject 001, period
  I: 11 disagreements"), open while three subjects or fewer have any; To do lists them flat, each naming its subject.

### Final review fixes: round-1 remainders — blinding, the arm guard, link elsewhere (2026-11-15; INT-3, INT-2, INT-4, INT-5, INT-1's over-masking, OWN-1; CHANGELOG "Fixed — final review, round-1 remainders …")
- **One rule for what D-15 withholds of the client's files** (`modeler_project/blinded_sources.py`, read through
  `deps.blinded_sources`): the delivery's rule (`intake_review.blinded_subjects`, `intake_decisions.blinded_files` and
  `blinded_sheets`) and the project's blinding list (`blinding.blinded_studies`: the files the listed studies' datasets
  were read from, and the sheets their readings or template rows came from) together. Every view that showed a client
  file reads it: Client files, the client review, a document's pages, the documents' list (`DocumentView.blinded`), the
  reading tray's figures (`FigureSuggestion.blinded`), the original, and the delivery's source view (no page drawn for
  such a file). `blinded_subjects` also blinds a delivery study the sheet form read as a listed one (the same name, or
  one of its `legacy_groups`), so both readers of one study withhold it.
- **The original (`GET /documents/{sha}/raw`) answers 409 `BLINDED`** for such a file until the MAP is signed. Its
  callers: the Digitizer (leaves such files out of its list and says so; a link to one says it is not drawn), the peek
  (offers no "Open the original" for a masked page), the value's source view (draws no page: the route gives none), the
  Start step's document viewer (says "original withheld"). No caller needs the original after a recorded reveal: the
  reveal (`POST datasets/{id}:reveal`, a reason on the audit chain) gives the dataset's values, never the file, and is
  unchanged; so no reveal path to the original was kept. **Cost, file-level as the delivery's rule:** a paper that holds
  a listed study's figure is withheld whole, so its other figures wait for the plan too. *(Incomplete, corrected in
  "Final review fixes round 3: downstream and blinding follow-ups" below: a library paper waits whole too, and the
  digits of every page of it are masked in the "Show the source" peeks of the Start step and the compound rows, not
  only in the Digitizer; the owner's decision is asked there.)* **Not changed:** the delivery
  report command (`delivery_report.py`, a command-line report, not a page) still prints the figures' captions.
- **A study blinded only by the project's list** is withheld on the sheet form as a delivery-blinded one is: its group
  says `blinded` (facts, options, answers and points withheld), reading its sheet, `:map` on it, `:finish` and
  `:confirm` answer 409 `BLINDED`. A group confirmed before (in the model already) says so ("It is in the model") rather
  than "read and confirmed once the plan is signed". Its datasets' reveal for a check is unchanged.
- **The sheet form's purpose against the delivery's** (`intake_review.joined_uses`, the join's two rules): `:finish`
  takes the delivery card's `intended_use` when the sheet form was given no purpose, and refuses another one; `:confirm`
  refuses a group whose datasets were read for another purpose; `:map` (Save these data) refuses the same; each with
  409 `PURPOSE_DIFFERS` naming both. A use the sheet form cannot state (internal validation, supportive) is refused, not
  taken: such a study is confirmed on its delivery card. **Not built:** the sheet form on the page still asks what the
  study is for (left empty, the card's is taken). *(Round 3: the other way round is refused too: once the sheet form
  loaded a study's data, its card's intended use is set, corrected or kept in a disagreement only to what they were
  loaded for; "Final review fixes round 3: downstream and blinding follow-ups" below.)*
- **The arm guard compares the ledger's conflict key** (`intake_review._arm_collision`, web `collisions` and
  `pairsMeet`): the same subject and field, the same period, analyte (by name) and matrix or one of them left out, for
  the values that take part in conflicts (`ledger_view.in_conflicts`). A matrix left out matching any is wider than the
  ledger (which reads no matrix as its own): a file that states none is most likely the other's matrix, so it is
  refused rather than let through. Values a request keeps in their study and arm (their analyte kept or first stated)
  are not compared with what they sit beside already, so "State it…" is never refused by it. The web compares a matrix
  by its written name, the API by the ledger's reading of it; where they differ, the API's 409 is what the page shows.
- **"Link elsewhere…" moves a place's values** (`linkPlaces`): a file's links are listed by the place they sent its
  values to, and one "Link elsewhere…" sends the union of those links' targets in one `values:assign`, so the facts
  (dose, fed state, LLOQ) go with the table. The analyte the links state is filled in and sent for all of them (as a
  first link with an analyte is); links stating two analytes ask for one. A file whose values went to two places lists
  both, says each is moved on its own, and the form names what stays where it is.
- **A blinded card's delivery fold** masks only decisions about a blinded study or its files; the clean-up of other
  files reads as on any card (INT-1's over-masking).
- **A table linked to two places before a re-read** (two partial links): its row says both ("Linked before, in part, to
  … and to …") and fills neither; the person links it again.

### Final review fixes: compound, products and the pages downstream of Inputs (2026-11-15; OWN-5, OWN-10, OWN-13, OWN-8 outside the layout dialog and editor, owner-job gap 11; CHANGELOG "Fixed — final review, compound, products …")
- **The elimination pathway (OWN-5):** offered are the pathways one value sets (`inputs.elimination_pathways`: of
  `PATHWAY_TARGETS`, those S0 counts, one harvested process carries and whose registry storage unit a stated unit
  converts to): the GFR fraction and the total hepatic plasma clearance. Left out, each for a reason a person can see in
  the table's note: the total renal plasma clearance (the registry gives it no storage unit, so a value would always
  wait to be typed again in PK-Sim's unit; it stays a target of a correction) and the pathways named by an enzyme
  (CLspec, CLint, Km, Vmax: the enzyme and often a process type are chosen too; they come with the literature or the
  client's files and are filed under Settle disagreements). A value is filed under the data plan's elimination item
  (REQ-elim.pathway) or, on a pathway's own row, under the item that owns it (the GFR fraction's REQ-elim.renal); S0
  counts the CPF ids, so both meet it.
- **Not changed, for the owner (SME):** the S0 rule needs no change. The template's condition lists are read by YAML
  split at every comma (`[system (HLM, hepatocytes, rCYP), …, fu,inc, …]` gives "system (HLM", "hepatocytes",
  "rCYP)", "fu", "inc"), so `evidence.assess` flags each piece and grades a source that states only its system
  (or "fu,inc" as one) as incomplete. Reading the list whole changes evidence grades: it needs the entries quoted in
  `core_small_molecule.yaml` (locked, SME-governed, a ruleset version bump). Until then the page joins a bracket's
  pieces when it shows them, and shows a piece of one without a stray bracket; the grade is the API's. *(Round 3: the page also
  joins "fu" and "inc" as the one condition "fu,inc"; it did not, as the skeptic found.)*
- **Accept refused (OWN-5):** a numeric value is never accepted without its value in PK-Sim's unit. Where the unit does
  not convert, the API names the unit (`EvidenceView.pksim_unit`, from the registry or the one harvested process
  parameter that takes it) and the row asks for the value in it; where nothing names one (the placeholder, a kind of
  parameter, a name the model does not take), the row files it under its pathway or parameter, or says why and links
  to Compound. There is no Literature page any more; nothing links to it.
- **A product's release (OWN-10, gap 11):** "release set" means the model holds a kept `form.<name>.type` under the
  product's name (its card's or a sheet-form name), as the status line counts formulations; a release proposed under
  another name is not matched to the product. "Needed" reads the readiness check "formulations of solid studies": a
  formulation it names that matches the product, or a solid study with no formulation at all (any product may then be
  the one). The formulation item opens a product card only when exactly one product is needed and not set; otherwise it
  stays on Products and dissolution. **Not built:** a form to give a formulation's release by hand (type, t50, shape
  with their source): with no dissolution data, the page says to add the dissolution file or ask the client. A done
  card with that item open shows "To decide" on its chip; its confirmation stays Done.
- **The Run page's studies (OWN-13):** `GET /studies` serves both lists (uploads first, then the catalog, each study
  once) rather than the Run page reading `GET /inputs`: one read, the same blinding, and the list is what a campaign of
  either path runs against. `source` tells them apart; the Run page's "Run campaign" (campaign:prepare, which stages
  uploads) counts the uploads only, so a pipeline project still runs from Review & sign. `GET /compounds/{c}/cpf`
  prefers the CPF Inputs assembles (a pipeline project could otherwise read the tenant-wide CPF of another project on
  the same drug, the store's old fallback). *(Corrected in round 3: only once that CPF holds a value; one that holds none yet
  answered 200 with an empty table where the page said "No values … filled in on Inputs".)*
- **The checks on Run and Review & sign (OWN-13):** said in the step bar's words with what to do and a link to the area
  of Inputs (To do for the minimum compound data and the build); the relation to To do's count is said in a sentence,
  not as a number (the count is the page's work model, which Run and Review & sign do not read). A link opens the area,
  not the item's own row: the page has no URL for one item. *(Round 3: two ways now land on their place, `?tab=formulations&add=product`
  on the form that adds a product and `?tab=todo&at=<place>` on the line of To do that asks the client; a single item's
  row still has no URL. The raw readiness text Review & sign still printed under the list is gone.)*

### Final review fixes: the gate, layouts and To do (2026-11-15; OWN-2, OWN-15, A11Y-2, CODE-2, CODE-3, CODE-5, CODE-9, CODE-10, OWN-8's layout part, the owner-job gaps 2 and 5; CHANGELOG "Fixed — final review, the gate, layouts and To do")
- **The read-only part of API 3 is built; per-cell "not data" is not.** A read table's numbers not read are listed on
  its region (`DeliveryRegion.silent_cells`, the first 50 of the coverage's own locators, each with its text, withheld
  for a blinded study's file, and why), so "Show them" names the cells. The why is the rule code's reading records
  (`CellUse.rule`), which the stored outcome does not keep: the table's layout is executed again on its grid for the
  view on every read (nothing is written; not memoised: round 3 corrected "memoised by file, parser, region and spec",
  measured 7 to 23 ms of a 0.28 to 0.37 s GET /delivery). Setting a single cell aside (the exclusion scope
  `cells`) stays the owner's review (§3 row 3). Where every study and product read from a file is confirmed with the
  sheet form (none signed on the delivery), a read table's whole "Not data…" is offered in To do as well as in Client
  files: nothing loaded or signed is lost.
- **§2.2.5 extended: what cannot be settled on this page is not counted.** Besides a blinded study's items and a layout
  being read again, a numbers-not-read item is left out of Next and of the counts, its row saying why, when all that is
  left of its file is numbers in read tables that are not plain numbers ("1,2" in a point-decimal table, `unparseable`,
  `time_unparseable`) and the cells in the same sheet row as one (its SD or n then qualifies no value: the reading
  records no rule for those, so the row is the web's reading, `noLayoutReads`). Only per-cell "not data" (the owner's)
  or a corrected file clears them; a file confirmed elsewhere (above) is counted, since its table can be set aside. The
  gate line, in To do and on the card, says in one sentence what still needs the owner's decision: the per-delivery gate
  (contracts §11.10) always, per-cell "not data" when an item waits for it.
- **A table the newest approved version cannot read** is said where it is read (`DeliveryRegion.newer`, `DeliveryMapping.
  tables[].newer`): the pipeline reads a table only with an approved version that has no error on its grid, so RLD stays
  on version 1 while version 2 reads Test's caption's product role (RLD's caption names "Reference" and "RLD"). The
  dialog opens at the row's version and table and offers "Correct the layout for this table…" there. **Not changed, for
  the owner (science-adjacent):** `intake_pipeline._choose` ranks the approved versions that read a table by the numbers
  they leave unread, then the facts they read, then the newest. A version corrected for one table that reads all its
  numbers is therefore also chosen for another table of the layout when it leaves fewer of that table's numbers unread,
  even if it reads fewer facts there: in the e2e, the version made for RLD (no product role, Mean, SD and %CV set aside)
  is then read on Test too, which loses its product role until Test's own correction (from version 2, with the same
  columns set aside) is stored and approved. The dialog's tables say which version reads each table, so this is seen;
  the ranking itself is not changed here.
- **"Read this sheet" from a sheet-form draft** reads the cells to mark as no sample from the draft's own sentence
  (`sheet_form`: "Cells say '12.3*', '>1000': mark them as 'no sample' or correct the file", `noSampleCells`), not from a
  field of the API. API follow-up: the draft's unread cell texts as data. The opener is a context of the Inputs page
  (`components/inputs/openSheet.ts`); elsewhere the draft shows no button.
- **The dialog's table** is the layout's header rows as written (their cells are each column's header, already shown
  unmasked in "Each column") and its first 5 and last 3 body rows masked; it is no longer "the table as the mapper is
  shown it" (the LLM's redacted payload, `mapping.redact`, is unchanged and still uses the header band code finds).
- **Layout form:** a row rule is set by the words its cell reads, matched whole (escaped); a rule written as a pattern
  is kept as it is and edited as text. A fact read once is kept, read from another place (a cell, the caption, a line
  beside the table) or no longer read; its pattern, and the label keys of a key-value table, are still edited as text.
  Fields, roles and statistics are named by their labels (`lib/words.ts`, `layoutFieldText`; the intake's ids in the
  technical detail).
- **To do keeps for the visit** the layout dialog (the queue, or one layout opened from a table's row) and what was
  marked as not data (`components/inputs/todo/visit.tsx`): both outlive the batch table's last row. Leaving To do for
  another area ends the visit (the list and an open dialog go), as before.
- **The dialog's focus safety net** (`Dialog.tsx`) watches the topmost panel for a focus that leaves to the page and for
  a change inside it (a removed focused element fires no event in every browser), and gives the panel the focus back.
- The slice-4 note "What is marked in To do is listed under the table with 'Restore…' for the visit" holds now after the
  last row too; the owner-job e2e's gaps 2 and 5 (CHANGELOG "Added — an end-to-end test of the owner's whole job") are
  fixed here.

### Final review fixes: cards, counts, demographics and repetition (2026-11-15; OWN-6, OWN-9, OWN-14, owner-job gaps 1, 3 and 7; CHANGELOG "Fixed — final review, cards, counts, demographics and repetition")
- **The study's individual on the delivery path (OWN-6, gap 1): one truth, chosen as the template's path does it.** The
  delivery's demographics form now also asks the PK-Sim population database and the sex of the individual PK-Sim
  simulates, the person's choice (D-29; as I4c asks it on the sheet form's card), and the landing sets the study
  record's `demographics` from them with the mean age, its range, the mean weight and height. How it is recorded, a
  deviation: two intake fields only a person enters (`individual_population`, `individual_sex`, `FieldDef.person_only`)
  entered through `:enter`, so the choice is a fact of the ledger with its reason, in the subject's digest and bound by
  the signature like every other, not a selection beside the record. Their values are checked where PK-Sim's names are
  known (the route against the harvested `HUMAN_POPULATIONS` and the study record's `Sex`; the landing again), not
  listed in `fields.py` (which holds no PK-Sim name). Not chosen, the demographics are held back and said ("Kept, not
  used by the model yet: … the study's individual needs …"), on the card, on Populations and in the signed record; the
  signature does not wait for them (no blocker added: the data plan's REQ-sys.demographics is about the data, unchanged),
  and once loaded Populations and individuals asks for the individual on the landed dataset, as for any study. Nothing
  is converted at the landing: an age in another unit than years (y, yr, yrs, year, years, or none), a weight not in
  kg or a height not in cm leaves the individual unset with the reason. The share of women and the ethnicity as written
  are kept (an individual is one sex and one population). The individual is read from the study's own facts (an arm's
  own over the study's, as every study-record field); a study whose arms state different demographics lands each arm
  with its own.
- **What the card says and what loads come from one function** (`intake_landing.study_individual`): the card's
  `DeliverySubject.individual`, the held lines and the landing; Populations and individuals reads the card.
- **The counts of what loaded (gap 3):** a study signed on the delivery is one study in the status line and the Clinical
  studies list however many datasets its landing loaded, its datasets said beside it ("1 study (3 datasets)"), all from
  the landing's own list (`landed_datasets`). A sheet-form study's arms keep being counted as the study records they
  were confirmed as (230-23-REF and 230-23-TEST are two), as before. The status line's datasets are the rows the model's
  study list is built from (one per study or arm); a metabolite's dataset of the same study is loaded and counted on the
  card and in the dialog, but is not a row of its own (GET /inputs keeps the parent's), so 230-23 with its parent and
  metabolite profiles reads "In the model: 2 datasets" on its card and "1 study" on the status line.
- **The facts after the route (gap 7):** the facts form mirrors what the landing asks once a route is known
  (`intake_landing._Record.read`: an oral study's dosage form and food state, an infusion's time) to offer them before
  the route is saved; the landing still checks them. API follow-up: a gap per route-dependent fact from the API, so the
  page reads it instead of mirroring the rule.
- **A values table folded to one check (OWN-9):** only when every row that needs the person comes from one check that
  has its own row in Checks (not a disagreement, which is settled value by value); the line opens that check's form.
  Its rows are still listed, and still "always shown" once the table is opened. *Round 3:* that never held on the
  owner's 230-23 (two checks mark its rows); the rule is now several checks, each with its own row in Checks (below).
- **The spot check's size, a question for the SME and the owner (not changed here):** on the owner's seed 111 values, on
  230-23 117, are drawn: a random sample of up to 100 (`intake_rules.yaml` `spot_check.size: 100`, the owner's decision
  6, at least 2 from each stratum) on top of every value always checked (`intake_review._always`: the study's key
  facts, derived and digitized values, values with a check accepted as is, cross-file facts and links). The old copy
  promised "a few values"; the page now says from the draw's own reasons why these are drawn, and a person still ticks
  each one. Whether the sample should be smaller (or scale with the study's values) is the SME's and the owner's
  (`intake_rules.yaml`, UNVERIFIED).
- **A recorded spot check is read, never drawn again:** the new `GET …/spot-check` returns the latest draw and its
  record; before, "Show the values to check" posted a draw, which wrote a new draw once the ticks were recorded.
- **Repetition (OWN-14):** a model check is not repeated when a To do group lists its gap (by the /inputs to-do's kind:
  `missing`, `process`, `formulation`, `regimen`, `demographics`, and the observed data while studies wait to be
  confirmed; *round 3:* for S0 also a compound value held for a person's check, below); the step bar's own line
  ("Waiting on you: …") stays, as it is the whole page's. Ask the client keeps the "needed for …" line and drops the
  chip. A card confirmed with the sheet form says who confirmed it in its head line
  only. The sheet form's path on a card signed on the delivery is pre-filled in the page from the delivery card's facts
  (entered or read: the number of subjects, a dose in mg, the dosage form, the purpose, fasted or fed, the route, an
  infusion's time; the sheet form's need names mapped from the intake's), each saying where it came from; this replaces
  round 1's API follow-up. Not reproduced, so not changed: "How the files were read" twice on one card (the skeptic
  found it once). Not in this group's list and left: a client file's name repeated on the first To do view (3 to 8
  times for a file with several kinds of work).

### Final review fixes round 3: speed and cache writes (2026-11-15; round 2's layout-dialog regression, OWN-7, CODE-4; CHANGELOG "Fixed — final review round 3, speed and cache writes")
- **One rule for the layout's cache keys.** `writeMapping` writes a layout's answer at its version and, when the answer
  is the latest by its own list of versions, with no version, on no table and on the table it shows: the API's rule for
  `GET …/mappings/{id}`. Chosen over passing the stored version from "Read this table…" or pinning the version after a
  decision (CHANGELOG): every key a dialog can read is written by the same rule, from the answer itself, never from what
  the cache happens to hold.
- **§2.1 "a decision click costs at most 2 requests", as built.** A decision on a delivery card, a selection in the sheet
  form, a choice: the decision and one read (the delivery page; the inputs' to-do; nothing, when the answer is the page).
  *Corrected in round 4:* a value accepted or rejected on Compound cost the decision and two reads in round 3 (the
  inputs and the other projects' offers), and pKa Save, Correct and "Keep the selected value" three (the inputs, the
  evidence, the offers); round 4 brings each to the decision and the inputs (round-4 sub-heading below). A spot check's record: the record and its card. Facts entered together:
  one `:enter` each and one read. Compound values entered in To do (or on Compound): one `POST /evidence` each, then the
  inputs (and, where Compound shows them, the evidence and the other projects' offers) and the step bar, drawn again when
  the readiness it says changed. **Deviation:** a confirmation costs more, because it loads data and every view of the
  data changes: the sheet form's confirmation reads the inputs, the evidence and the client data, and the delivery and a
  card where one of its subjects reads the same source (3 to 5 reads); the signed confirmation, when its dialog closes,
  the delivery, the inputs, the sheet form, the client data and the evidence (up to 5), the other cards marked stale. So
  do the background events that are not decisions (an AI reading or the literature search ending). Next's prefetch of a
  page a link leads to is not counted (it reads none of this page's data). *Corrected in round 4:* prefetches did
  appear: about twenty followed every step-bar redraw (25 measured after a study's sheet-form confirmation); round 4
  turns them off on the step bar and Inputs' own links, and measures what each confirmation reads again.
- **The step bar follows the readiness (replaces slice 4's "redrawn only after the compound values are entered").** It
  is drawn on the server, so `InputsWorkspace` draws it again when what it says about Inputs changes (the readiness's
  state and failing checks in the inputs' answer), whatever changed it, and only then. Known gap: Review & sign's own
  state on the bar (a signed MAP that a change to the inputs makes stale) is not part of that answer; it is current on
  the next page drawn (a change on Inputs that moves it also changes the readiness in every case seen, but this is not
  guaranteed).
- **A reading a decision asked for is followed by two signals.** The delivery page says it is reading (`running`) and
  is read every few seconds until it is not; the layout dialog's answer says its files wait to be read (`waiting`), and
  when it stops waiting the page and the cards shown are read again. Before round 3, every part of the page read the
  page again when it was drawn, which hid that the first signal alone can miss a reading that ends just as the page is
  read (seen once in three runs of inputs-task-first's corrected-layout test). Known gap: a decision whose reading ends
  after its dialog is closed relies on the first signal alone. *Superseded in round 4:* both signals caught a flag's
  turn, and both could miss it (the API said "not reading" beside data read before the reading ended; a read of the
  layout sent before the approval overwrote its answer); the page now follows the runs the delivery page names, and the
  API reads the runs first (round-4 sub-heading below). The dialog's signal is removed.
- **The visit holds its reads (CODE-4).** Inside `HeldReads` (Inputs) an answer read during the visit stays fresh until
  a change marks it stale, so an area shown again reads nothing; what was read before the visit is read once when shown.
  Consequence, owner's note: another reviewer's change is shown after this person's next decision on it (a 409 says it
  in the server's words, §2.2.6), on a file's reading ending, or on the next visit; switching areas no longer reads the
  page again. Other pages keep reading on every mount, as before.
- **`useMutation` callers outside Inputs** say what they change too (CHANGELOG lists them). Where a page is drawn on the
  server (the dashboard's projects, the project page, Start's and Review & sign's step bar, the campaign monitor), the
  change draws it again, as the broad refresh did; nothing else is read for it.
- Round 2's other minors from the gate-todo skeptic: the "memoised" wording above is corrected (not memoised); a card's
  "Read this sheet" ask is spent when its file's row is closed; "Restore…" under "Marked as not data just now" says what
  it restored and its Cancel keeps the entry listed. Not covered by an e2e: the last two (unit-level behaviour of the
  visit; the specs that pass through them, inputs-task-first and inputs-owner-job, still pass).
### Final review fixes round 3: cards and gate follow-ups (2026-11-15; the five "Confirmed by" specs, OWN-9, OWN-14, the spot check made stale by the individual, the gate minors a to e, the owner-job flake, CODE-1; CHANGELOG "Fixed — final review round 3, cards and gate follow-ups")
- **A values table folds under several checks (OWN-9, corrected).** Round 2's rule (one check for every row) never held
  on the owner's own 230-23: the analyte missing marks all 76 rows of each arm's table and "more than one LLOQ in the
  profile" marks 6 of them, because of the same missing analyte. The rule is now every row that needs the person marked
  only by failed checks that each have their own row in Checks; the line names each with its count and a link to its
  row ("State it…" for the analyte, "Decide it…" otherwise), and "Show the 76 values". A disagreement, or a failed check
  settled elsewhere on the card (a fact, a required item), still opens the table. The checks are named from their own
  messages (the part after what they are about, before their reason), not from a list of check codes kept in the page.
  Measured on the review copy cut to the owner's state (seq ≤ 12): 230-23's card is 4,902 px folded (15,870 px in round
  2), 10,441 px with one 76-value table shown.
- **The minimum compound data said in To do (OWN-14, corrected).** /inputs lists an S0 gap a value was found for as that
  value's own row (`review`, `correct`, `pka`, `unit`, `conflict`, or an elimination pathway's `process`), never as
  `missing` as well. Since every S0 gap is
  one of these rows, a failed S0 check with any of them listed on the compound is said in To do and not repeated among
  the model checks. Round 2's note above ("by the /inputs to-do's kind: `missing`, …") held only for a compound with no
  value found.
- **The individual before the spot check; the spot check's digest (owner question).** A study's individual (the PK-Sim
  population and the sex, D-29) is entered as two ledger facts, so it is in the subject's digest and the draw's seed
  (`intake_review.draw_spot_check`): chosen after the spot check is recorded, the spot check is stale and a new draw asks
  for new ticks for the part of the random sample drawn anew (how many depends on the ledger's head, which seeds the
  sample: on the review's 230-23, 55 new and 62 carried over when round 2 chose it, 44 new and 73 carried over at round
  3's check; corrected in round 4: the page promises no number of them). Not changed (the digest and the draw are SME-governed, and
  the facts a signature binds include the individual): the card puts the individual first in its open work, counted
  like its other rows (its row says "the spot check is then drawn again" where one is drawn already; the signature does
  not wait for it, as before), the spot check itself says "Choose the study's individual first" while it is not
  recorded, and every form that enters a fact on a card with a spot check drawn says before Save that it is drawn again
  and which ticks carry over: the values always checked, counted (`DeliverySpotState.always`, the draw's own list: 17 of
  230-23's 117), and of the random sample only those drawn again. How many of the sample carry over is not said: it is
  known only once drawn (the seed is the ledger's head, so a new entry draws a new sample), and computing it would be a
  second draw. **Owner question:** should a person's own choices of the individual (`individual_population`,
  `individual_sex`, `FieldDef.person_only`) be left out of the spot check's digest and seed? They are words a person
  chose, not read from a file, so no draw includes them (`intake_review._always` and the sample take numbers, censored
  values and what is read from a figure, computed, linked or read from another file); they still change the digest and
  the seed, and they are bound by the signature either way.
- **What a layout approval moves, said before it (gate minor e).** The pipeline reads each table with the approved
  version that has no error on its grid and leaves the fewest numbers unread, then reads the most facts once, then is
  the newest (`intake_pipeline.choose_version`, which `_choose` now calls; the rule is unchanged). The API asks that
  same function, for a version waiting for approval, which tables of the layout it would move and what changes for each
  (`DeliveryMappingTable.moves`); the dialog says it above "Approve" and the approval's sentence names them. Only the
  tables a version of the layout reads now are asked (`used_in`); a table of the same layout that no version reads is
  not listed (none on the seeds). **Still the owner's (recorded under the gate's fixes above):** whether the ranking
  should keep the facts a table reads (its product's role) over the numbers it leaves unread.
- **The silent cells are not memoised (gate minor a, corrected).** The note above said "memoised by file, parser, region
  and spec": no memo was built (a module-level one was removed for `tests/architecture/test_process_state`). Each GET
  /delivery executes a read table's layout again; measured on the 9-file review projects that is 7 to 23 ms of the 0.28
  to 0.37 s the page takes, so none is added.
- **The places on a delivery card are the subject's own (CODE-1).** Since slice 3 several cards are open at once (up to
  three studies, plus the first to confirm and any the person opens), so a place named only by its fact
  (`delivery-gap-route`) was on the page once per card and the page's look-up took the first. Every place To do or a
  card's own list links to is now `delivery-<place>-<subject>-<id>` (`inputsWork.cardPlace`; a check's place was its
  own already, its id being the subject's), its HTML id with it, and the page looks inside the item's card first. A
  subject is one card on the page, so its subject is enough; the look-up inside the card covers a second instance.
- **Smaller ones:** a Restore says what it did on the line that said the marking; a card's "Read this sheet" is taken
  once (the page forgets it once the reader opens); every field of the intake vocabulary has a label in the layout
  editor; the owner-job e2e counts once nothing is being read again (three runs in a row passed; one earlier run in a
  batch failed later in the flow on a 500 from GET /inputs, the web proxy's connection to the API reset under load,
  not on the arrival count; `inputs-task-first.spec.ts`'s two-file "Mark as not data" batch once waited past 15 s for
  its row to update in a loaded batch and passed when the spec was run again, untouched here).
- **Not in this group:** the gate-todo review's regression (the layout dialog opened on a table with no version, right
  after "Read this table…", keeps "waits for approval" after an approval: `writeMapping` never writes that key) was
  still open at this group's base and was another round-3 group's (speed); not touched here, to keep one fix of it.
  Corrected in round 4: round 3's speed group fixed it (`writeMapping` writes the answer under every key a dialog reads
  a layout by; "Final review fixes round 3: speed and cache writes" below and its CHANGELOG entry), merged with this
  group at 415cfde, so it is no longer open.
- Nothing was stopped for a locked file, an SME rule or an owner decision; no boundary exception was added.
### Final review fixes round 3: downstream and blinding follow-ups (2026-11-15; OWN-8, owner-job gap 11, the words, the risks round 2's skeptics found, INT-2 the other way round, the blinding scope; CHANGELOG "Fixed — final review round 3, downstream and blinding follow-ups")
- **Review & sign in words (OWN-8):** `StepBlocked` prints what the API said only where no list of the earlier step's
  checks says it, and then in the step bar's words (`readinessText`); `PlanCanvas` gives it every `inputs_ready`
  refusal (not ready, not put together, changed, no CPF or no study), not only "not ready". The same refusal can reach
  the open plan later (the inputs change while it is open: `GET /plan/review`, a change to the plan, the signature):
  those messages go through `readinessText` too, which leaves any other refusal as it came. The Run page passes no
  detail. No other page prints the readiness text: the step bar and To do already say each check in words; the plan's
  stale banner names artifact versions, not checks (left). A check's other ways read as the step bar's ("(add a
  product on Products and dissolution, or ask the client on To do)"), not two bracketed links. *(Round 4: the skeptic
  found the lever said twice there, in the sentence and in brackets; Review & sign now says the situation and each way
  once, "no product is here; add a product on Products and dissolution, or ask the client on To do", and only where it
  fits.)*
- **Gap 11, the ask that was missing.** A per-product item (`per: solid_product`, today REQ-form.release) is judged per
  product (`study_requirements.product_requirements`), so a tablet study whose delivery names no product had its
  release model asked nowhere. `study_requirements.unnamed_product_items` (unlocked code; the locked templates are read,
  not changed) adds, for each delivery study whose dosage form is solid (the study record's choices the readiness check
  reads as solid) while no value of it names a product, no product of the delivery has values, the model holds no
  formulation and no dissolution profile is here, the item as the study's own line of the client request: "The
  formulation or dissolution data of the product the study used (no file names the product) · OJ-101", needed for the
  model itself. It is not an item of the study's card, so the study's signature does not wait for it and no disposition
  is offered for it (the card's route answers only the card's items): the line goes once a product of the delivery has
  values (its own card then asks for its release), a dissolution profile is here or the model holds a formulation.
  **Deviation:** derived from the delivery's studies (the ledger). A study confirmed only with the sheet form, with no
  product, gets no ask line: its readiness item says to add a product or ask the client. *(Corrected in round 4: the
  client request download (the data plan's `client_request`) already asks for the release model of the product
  (dissolution) with no product named, as the skeptic found on clientamide-pbpk; and the ask line is derived from the
  inputs too now, see round 4 below.)* **Not built:** a
  form to give a release by hand (as round 2 recorded). On a copy of the review data the four Clientamide projects
  now ask it for their five solid oral studies (one line, EX-101 and CL-1 to CL-4); the Exampleamide projects, whose
  delivery names products, ask it per product as before.
- **The lever named:** "add a product" (the brief's products list on Products and dissolution; its form opens, focused,
  from `?tab=formulations&add=product`) is named by the step bar ("a tablet study has no formulation (add a product on
  Products and dissolution, or ask the client)"), Review & sign's line (its fix sentence and a link), To do's
  formulation row (when no product of the client's is here) and the formulation item's own text. "Ask the client" opens
  To do on the line that asks (`at=todo-ask-REQ-form.release`, focused; the group when there is none). The solid study's
  row on Products says "no product here: add the product it used (“Add a product”, above) …, or ask the client" when
  no product (the client's or the proposal's) is here, "no dissolution data for a product here" when products are here
  without a profile, and "use a product's dissolution profile as its release, above" only when a profile is. *(Wrong,
  corrected in round 4: this note said the step bar cannot tell these cases apart and so names "add a product" whatever
  the case. It could: the step bar and Review & sign read the steps, and the steps can carry what the project holds. On
  the owner's review project, whose products have dissolution profiles, "add a product" opened an empty form instead of
  "Use this profile as the release". Since round 4 the Inputs step carries the lever that fits (see round 4 below).)*
- **The words:** a product card's done line says the release is said "above" (it is); "fu,inc" is one condition again
  (`bracketed`: a known pair the template writes with a comma and no bracket, `COMMA_CONDITIONS`; either piece alone
  is said whole, since "fu" alone would read as the plasma's fraction unbound and no template has a lone "fu"). The
  grade the API gives each piece is unchanged (SME, as recorded above).
- **The compound page's CPF:** `GET /compounds/{c}/cpf` answers the CPF Inputs assembles only once it holds a value;
  otherwise the stored one, else 404 (the page's "No values … filled in on Inputs").
- **The formulation problems one by one:** the formulation item carries its problems as a list (`details`, the readiness
  check's own; `todo` is untyped, so no contract change), and the page splits the joined message only before a
  problem's study (`formulationParts`), so "formulation 'X' is of type 'Y'; the builder places …" is one problem said
  by its own rule.
- **INT-2 the other way round:** setting or correcting a delivery study's intended use (`:enter`), or keeping one
  purpose in a disagreement between two (`:choose`), is refused (409 `PURPOSE_DIFFERS`, naming both) when the sheet
  form loaded its joined data (a client dataset a person accepted, of its `legacy_groups` or of its name) for another
  purpose (`intake_review.joined_purposes`). A reading not confirmed yet does not hold the card (`:confirm` refuses it
  instead, as round 2 built). The refusal says to keep the card's purpose or take the sheet form's data out of the
  model first; the card's form shows it in words (the API's message, under the form that sent it). Purpose words are
  one list now (`intake_review.use_words`, also the sheet form's refusal). **Not caught:** a purpose read from a file
  delivered after the sheet form loaded the study (a value read, not set by a person) is not refused: it shows as the
  card's value and, if it disagrees with an entered one, as a disagreement whose keeping is checked; and
  `POST datasets/{id}:decide` with ACCEPTED, called directly (the page offers only REJECTED and PROPOSED there), is not
  purpose-checked (the remainders skeptic's minor note; left).
- **The blinding scope, a decision for the owner (round 2's skeptic, side effect 1).** A file is withheld whole as the
  delivery's rule withholds it, and that now includes a library paper one figure of which was digitized for a study on
  the project's blinding list: its original is not served, its other figures are not offered to the Digitizer, and the
  digits of every page are masked, also in the "Show the source" peeks of the Start step and the compound rows (a
  compound value quoted from that paper cannot be checked against its page until the plan is signed). Kept as it is
  (conservative). The page now says why where it bites: the Digitizer's line and the peek name the blinded study the
  file waits for and that the whole file waits (`DocumentView.blinded_by`, `DocumentPage.blinded_by`: additive). **Owner
  decision:** (a) keep the whole paper withheld, as now; or (b) withhold only the blinded dataset's figure and the
  pages it was digitized from, so the paper's other figures, and the pages a compound value is quoted from, stay open.
  (b) needs the figure's page kept with the dataset (the Digitizer keeps the page it was drawn on) and a page-level
  rule in `blinded_sources`, the documents' pages and the original (which would then be served with the blinded pages
  left out, or not at all).
- **The blinding scope, the name match (side effect 3):** a delivery study is blinded by the project's list when its
  name is a listed study's (or the sheet form read it as one), compared whole on the readers' key (`blinding.study_key`:
  case, spaces and punctuation aside), never as a prefix or a part: "Study 1" listed leaves "Study 10" open (a test).
  The card and the page's row say why (`DeliverySubjectRow.blinded_why`, `DeliverySubject.blinded_why`: "the project's
  blinding list names it (study STUDY-1)", "it is entered for external validation on its card", "the project's
  blinding list holds a dataset loaded from it (study …)"), so a wrong match is seen; the To do rows of a blinded
  delivery study say it too ("Blinded until the plan is signed, because …"). Left as it is: the key ignores
  punctuation, so "230-23" and "23-023" are one study for blinding, as for the join (§2.1). *(Round 4: the why was said
  on delivery-path cards and To do rows only, not on a card confirmed with the sheet form (its visible withheld line),
  the Clinical studies list's chip or the readings' withheld lines; and a reason that is the list's now ends with why
  the list holds the study, "…(study STUDY-1): a dataset of it is entered for external validation".)*
- **Left, not in this group's list:** Review & sign's "Overall Data" still lists the CPF by its ids and PK-Sim's units
  ("bind.fu 0.7", "phys.logp 0.21 Log Units"; round 2's skeptic, outside OWN-8's readiness line). The diagrams beside it
  name the same ids; saying the list in words is for the Review & sign page as a whole. The purpose refusal on the card
  is checked by the API tests only: the card shows it through the form's existing problem line, not by a browser test.
### Final review fixes round 3: accessibility and forms (2026-11-15; A11Y-1, A11Y-3 to A11Y-11, CODE-6, CODE-7, CODE-8 a–c, INT-12, OWN-16; CHANGELOG "Fixed — final review round 3, accessibility and forms")
- **One rule for focus:** a control that removes itself hands the focus on (`kit/focus.ts` `focusSoon`): an answered
  question to its row's own button, a cancelled form to what opened it, a cleared bulk bar to "Pick every file" (or the
  first picked row). A dialog that closes gives the focus back only to something that can take it inside the dialog still
  open under it, else that dialog's panel (`kit/Dialog.tsx`, extending round 2's safety net); "Sign and load" stays
  focusable while it is sent. Not changed: after a successful decision whose row stays (Accept as is on a card's check),
  the focus goes to the row when it has a control left, else stays where the browser puts it; the list-level rule
  (`focusAfter`) is unchanged. Corrected in round 4: a form opened in place did not always take the focus (the
  demographics form on its first open of a page, from Populations, a card or the spot check's link; "Enter another fact…"
  gave it to the reason field): see round 4 below.
- **Live regions:** the counts are said by a status region of the status line only when they change after the page has
  read its work, 1.5 s after they settle, as "Now … missing, … to confirm, … to decide." (not appended to each decision's
  words, as the reviewer suggested: a decision's answer arrives before the cards it changes are read again, so the
  counts in its words would be the old ones). A refusal is said by its alert where it is shown, not again in To do's
  live region; a layout decision in the dialog's own region only.
- **Keyboard and the bulk bar:** the page keeps the bar's height clear for the focus with `scroll-padding-bottom` and, for
  a browser that scrolls only what is outside the window, a `focusin` guard that scrolls a covered row above the bar.
  Past two picked files, where each goes is folded under one line.
- **Context labels:** a repeated control's name starts with the words on it and then says what it is about (WCAG 2.5.3);
  e2e/inputs-a11y.spec.ts checks that no two visible controls of To do (two link editors open), Populations and
  individuals, or Client files share a name on the 9-file seed. Not checked there: the template project's Clinical
  studies ("Show the points", Linear/Log, "Confirm the selection" were named in the code; corrected in round 4: the
  template project's names were not all fixed, "Leave the dataset of EX-101 out" and the item peek repeated once per file,
  and with several study cards open their forms' names repeated with no study: fixed and scanned in round 4, below); the
  compound rows' fields keep their names with the parameter's id ("value for phys.mw"), which the specs read; putting
  them in words is left.
- **Headings:** each area has an h2 of its own (`sr-only`; the bar names the area on screen).
- **The page's one primary (OWN-16), a deviation in form:** forms inside an area keep the `primary` class (their main
  action) but are drawn tinted (`[id^="inputs-panel-"] .btn.primary` in inputs.css); "Next" is the one filled button. A
  dialog over the page keeps its filled primary.
- **CODE-6:** every card form says what is missing when pressed instead of a silent disabled button, except the layout
  form (slice 4's recorded exception) and two older compound forms whose disabled button now has its reason in text
  beside it (a compound row's Add; a statement's Correct in To do's settle form). The spot check's "Record the spot
  check" stays disabled until every value is ticked (its count says why).
- **"Use last" (INT-12), corrected:** slice 4's note above ("kept per project and kind of decision …; the kind is the
  button's word unless a form names it") no longer holds: every form names its kind, the key holds the person signed in
  (the ID token's subject, hashed; "" with the DEV sign-in) and the project, and sign-out forgets them. Not covered by an
  e2e: the sign-out (the DEV sign-in has none; oidc-signing.spec.ts runs only with a test Keycloak). The reason is
  emptied after a decision whose answer says it was made (CODE-7); a refusal keeps it for the next press.
- **CODE-8 c, decided:** MATRIX_MISSING is a fact (the card's facts form asks it, with "Accept as is…"), so To do counts it
  on the study's facts row as Missing, no longer as a check to decide under "Settle disagreements".
- **OWN-16, Link head:** a file's values are counted as its rows say them: a table's cells are values, a fact read beside
  them a fact ("6 files · 355 values and 11 facts"); the rows' buttons and the link item's label say the same.
- **Owner questions:** none new. The hero pill's darker ink applies on every page's head (one rule).
- **Seen once, not this group's:** in one run inputs-task-first's "a table the newest layout cannot read" timed out
  waiting for RLD's row to leave To do after its corrected layout was approved and read (the page still showed version
  1's 24 numbers; the API had RLD on version 3 with none); it passed on the rerun. A timing gap in when the page reads
  the delivery again after a re-read, for the speed group. *Found and fixed in round 4* ("Final review fixes round 4:
  request budget and the RLD flake" below).

### Final review fixes round 4: downstream and blinding (2026-11-15; round 3's regression "add a product" named whatever the project holds, blinding scope b, the gap 11 deviation; CHANGELOG "Fixed — final review round 4, downstream and blinding")
- **The lever follows what the project holds (round 3's regression).** One reading, on the server
  (`modeler_project.formulation_way`), from the readiness check's problems and what is here: `use_profile` (a
  dissolution profile read as a curve with a Weibull fit, the rule of the card's "Use this profile as the release";
  `products`: their products, a product the study names first), `add_dissolution` (products here, from the delivery
  with values, the dissolution register, the sheet form's compositions and the proposal, none with such a profile),
  `add_product` (no product at all), `choose` (several formulations, a study naming none); none for the other problems
  (a formulation not complete, a type the builder does not place, a study record not complete), where only the area is
  named and To do's item says each problem. It is carried by the Inputs step (`StepRow.formulation`, additive: the step
  bar and Review & sign read `/steps` already, so no request is added) and by To do's formulation item (`way`, in the
  untyped `todo`), and said by one pure function (`lib/words.ts` `formulationWays`: what is open, the situation, a
  sentence, the ways as links) for the step bar, Review & sign, To do's row and item, the Model checks line and
  Products and dissolution's line per tablet study. `?tab=formulations&release=<product>` opens that product's card at
  its release, the first control focused ("Use this profile as the release" where one profile can; what to add where
  none can); a product with no card (the proposal's, a profile of no product) opens Products and dissolution at the
  profiles of no product, else the proposal's list. *(Round 5: wrong as a landing: the proposal's list took the focus on
  the product's "Change", where nothing adds dissolution data; a product with no card now opens Add data on the
  dissolution files, focused, and a card with no profile its "Add its dissolution file…".)* The step bar is drawn again when the lever changes (a profile or a
  product added), not only when the checks do. Inputs no longer reads `/brief` for the lever (round 3 added that read).
  **Found on the way:** a profile's fit is used as a release only once a person confirmed its product's dissolution
  data (`client_review.product_confirmed`; the API's 409 otherwise), and on 7bb1 both products with profiles are still
  to confirm, so "use a product's dissolution profile as its release" would have landed on a button the API refuses.
  The way carries `ready` (the first product's data confirmed; a confirmed product is offered first *(round 5: the sort
  by `ready` ran after "a product the study names first", so a confirmed other product came first, against the
  module's docstring, and a study naming its product was offered another product's profile; the way is now read for
  each study, the named product first)*): while not, the
  words say the order ("confirm a product's dissolution data, then use its profile as its release") and the card's
  release line offers "Confirm its data first", which takes the focus to the product's Confirm. **Left:** a product
  signed on the delivery whose sheet-form group was never confirmed still has its profile refused (the rule reads the
  sheet form's confirmation only); the card then sends the person to "Confirm with the sheet form instead". Whether a
  delivery signature should count for it is for the owner.
  **Deviation:** the item opens the first product's card and is that card's own work only when one product is named; with
  several (7bb1: Test 10 mg and Brand 10 mg) the person chooses which product the study used, so no card counts it.
- **Checked on a copy of the review data:** exampleamide-pbpk-7bb1 (four products, two with profiles still to confirm,
  two tablet studies with no formulation) gives `use_profile` with Test 10 mg and Brand 10 mg, `ready` false, on
  `/steps` and on the item, so the step bar reads "a tablet study has no formulation (confirm a product's dissolution
  data, then use its profile as its release on Products and dissolution)", and in a browser on that copy the link lands
  on Test 10 mg's card with "Confirm its data first" focused, To do's row and Review & sign say the same, and 231-24's
  card and list chip say why it is withheld; the other projects (no failing formulation check) give none; the reading
  costs about 0.1 s on `/steps` and `/inputs`, only while that check fails; the owner-job seed (no product) keeps "(add a product on Products and dissolution, or ask the
  client)" (e2e). The same in a browser on a seed with products and profiles (e2e `inputs-owner-job`, second test: the
  link lands on Test 10 mg's card, "Confirm its data first" focused; no empty form opens; confirmed, the card offers
  "Use this profile as the release" and the step bar says to use it; used, the formulation check is met).
- **Blinding scope (b), the why wherever a study is withheld.** A client-review group gains `blinded_why` (additive): the
  delivery's reason for the study it is joined to (by `legacy_groups` or its name), else why the project's blinding list
  holds the study of its name (`blinding.external_why`: "the plan places it in S5 (external validation)", "the study
  split proposes it for S5 (external validation), before a plan", "a dataset of it is entered for external
  validation"). A delivery reason that is the list's ends with the list's own ("the project's blinding list names it
  (study STUDY-1): a dataset of it is entered for external validation"), so the card says why the list holds the study,
  not only that it does. The page says it (`blindedWhy`: the card's delivery reason first, else its group's) on a sheet-form
  card's visible withheld line, under the Clinical studies chip, in the readings' withheld lines and on the sheet-form
  rows of To do. On 7bb1 the card of 231-24 now says "Withheld: study 231-24 is blinded until the plan is signed,
  because it is entered for external validation on its card. It is in the model; …", which also makes visible the
  state round 3's skeptic found there (loaded for building by the sheet form, entered for external validation on the
  card): **not changed**, an existing state INT-2 the other way round now refuses to create; whether to flag it on the
  card is for the owner. *(Round 5: "wherever" was not so: Populations and individuals, a product's card head and the
  dataset lines gave no reason; they do now, and the reason's words lead to where it is changed: the purpose on the
  delivery card, where "Change the purpose…" is offered, or the plan's roles.)*
- **Gap 11's deviation closed: the ask on both paths.** With no product here at all (`add_product`), To do's formulation
  item carries the client request's line for each tablet study it names (`ask`; `study_requirements.unnamed_product_request`,
  the same item, label and wording as the delivery's `unnamed_product_items`), so a study confirmed with the sheet form
  only is asked too; the page joins the two (`askLines(delivery, inputs)`: one line per requirement and wording, each
  study once, by its name as the join compares it). **Left:** the delivery's line still follows its own condition (no
  product of the delivery with values; a product only the proposal names does not stop it), while the inputs' follows
  "no product here at all"; where a product is only proposed, the delivery asks for a delivery study and the inputs do
  not ask for a sheet-form-only one (the step bar then names "add a product's dissolution data, or ask the client",
  whose line is the group "Ask the client" when none asks). *(Round 5: closed: the inputs' line follows the study's own
  way, asked whenever it offers "ask the client", add a product or add a product's dissolution data.)*
- **Owner questions:** the 7bb1 state above (a study loaded for building, entered for external validation later): flag
  it on the card, or leave it to the plan's split? No other new question.
- **Not built:** a form to give a release by hand (as rounds 2 and 3 recorded). The Every dataset list's "blinded until
  the MAP is signed" line (a dataset, not a study card) does not say why; the dataset's purpose is shown beside it.
  *(Round 5: built: the dataset says why, from its study's reason on the project's blinding list.)*
### Final review fixes round 4: accessibility and cards (2026-11-15; round 3's a11y-forms and cards-gate skeptics: A11Y-5, A11Y-7, OWN-16, the spot check's honesty, the records; CHANGELOG "Fixed — final review round 4, accessibility and cards")
- **The demographics form's focus.** The form moves the focus itself once its field can take it (an effect on the
  vocabulary's loading, once per opening), not by `autoFocus`, which the "loading the words…" select swallowed on a
  first open. Where it lands is the opener's to say (`focusOn`): "Choose the individual…" (on a card, on Populations, the
  spot check's link) on the individual's PK-Sim population, every other opener on the first field a person fills. The
  spot check's link no longer focuses by a timer; the row scrolls into view and the form takes the focus. A value's
  "Correct" now opens on its Value (its button stays, so this was not required; one form, one field taking the focus).
  *(Round 5: once per opening was not enough. The spot check's link pressed again with the form open only scrolled, and
  Populations' form, keyed by the stated demographics (round 4 left it as pre-existing), was remounted on each field a
  save wrote, the focus jumping back to the population each time; both fixed in round 5, below.)*
- **Context labels, finished.** Every repeated control on a card names its subject ("study 230-23"), after the words on
  it (WCAG 2.5.3); a stated fact also by its value and file; a values table by where it starts in its file
  (`words.anchorPlace`, from its first value's anchor: "page 4, table 1", "sheet Fasting from cell B22"); a sheet-form
  item, chart or dataset by its source's file (`words.sourceNamed`). e2e/inputs-a11y.spec.ts now scans Clinical studies
  with every study card open on the 9-file seed, and a second project, the client-data template's (EX-101 from two files,
  four studies in one workbook), every area, every card open. **Left as it is:** the spot check's tick radios ("matches",
  "does not match") and a values table's sort buttons repeat by design inside their table, under its caption and the
  row's legend; they are not in the scan's default view (the scan sees the page as it opens, with every card open, not
  every value table shown and every spot check drawn). *Corrected in round 5: they were not the only repeats. With the
  values tables shown, their pages, the lists of more checks and a spot check drawn, a urine interval's Show and Correct
  (four per table, the interval left out of the name), the spot check's source buttons and the pagers ("Show 8 more",
  "Show all 42") repeated too, the names spelled `excretion.amount`, and with every product card open "Use as release"
  and "Confirm its data first" repeated; all fixed in round 5 (below), and the radios and the sort buttons are now the
  only repeats, which a round-5 e2e scan of Chromium's names asserts.* *Corrected in round 6: true only on the e2e seed
  and the copies round 5 scanned, and the scan read only names without ": " (Chromium's snapshot quotes the others, and
  its pattern skipped them). On the owner's project (7bb1) 230-23's two datasets were named and shown alike, the studies
  table's "not stated" button repeated, and the formulation-way button did; fixed or recorded in round 6 (below).*
- **Phone and message:** the phone rule for Client files comes after the desktop rules and is as specific as the kit's
  `.table-scroll table` *(corrected in round 5: its descendant selectors and the kit's width also reached an open file's
  own tables, which were cut on a phone; fixed in round 5, below)*; a message is cleared by one effect on the area
  chosen (not in each handler), so no way of changing the area keeps it. A message said while the page loads (before it settles on its area) stays.
- **The spot check, decision by decision (the API's rule, checked, not guessed; `intake_review._stale`):**

  | Card decision | Drawn again? | Said before Save |
  | --- | --- | --- |
  | a fact entered, "Enter another fact…", "Correct", the individual | always (a new value, or one superseded) | yes (round 3) |
  | "Accept as is…" | when a value of the check is outside the draw | yes, with the count (`DeliveryCheck.outside_draw`) |
  | "State it…" (the analyte) | only when values are computed from the check's values | yes, with the count (`DeliveryCheck.computed`) |
  | "Keep this value" | always (the others set aside) | yes |
  | "No…" to a file's link | when the file gives values (they leave the study) | yes |
  | "Yes" to a link naming several studies | yes (the card's study is merged into the one chosen, read from `Ledger.link_files`; not run in a test) | yes |
  | "Yes, the same study" (one study) | only when values wait to be computed from the file's (an SD from an SE, a series' n) | **no** |
  | "Record it" (a required item) | never (no value changes) | nothing to say |

  **Known gap:** the plain "Yes, the same study" is not foreseen: telling it would mean running the ledger's derivations
  with a confirmation not yet made (`ledger_compute.derivations` with one more `LinkConfirmation`); left, and recorded
  here. No link waits on the review copies; on the API test's project confirming the late samples' link changed nothing
  (they state an SD: nothing waits to be computed). **Deviation from the
  task's list:** "State it…" draws the spot check again only where something is computed from the values (none on the
  owner's 230-23), so its warning shows only then; settling a required item never does, so it says nothing.
- **Records corrected in place:** the round-3 accessibility entry and its §5 note (the demographics form's and Enter's
  focus, the template project's names, the phone files table, the message kept by the status line), the round-3 cards
  entry and §5 note (55 new ticks and 62 carried over were round 2's, from that ledger head; the spot check's link did
  not focus anything; the `writeMapping` regression is fixed by round 3's speed group).
- No locked file, SME rule (draw size, digest and seed rule, requirement levels) or boundary exception was touched. The
  API change is additive (two counts on a check).

### Final review fixes round 4: request budget and the RLD flake (2026-11-16; OWN-7's remainder, round 3's risk (a), the corrected-layout row in To do; CHANGELOG "Fixed — final review round 4, request budget and the RLD flake")
- **How a reading is followed, as built (replaces round 3's "two signals").** The API reads a project's runs before
  anything a run writes (`_Scope.refresh`), so the delivery page's `running` and a layout's `waiting` describe the moment
  before its data was read: "not reading" means the rows are current, and a reading that ends while the answer is put
  together leaves it saying "reading". The page polls the delivery page while it reads, and reads again what a reading
  changes (the cards and layouts, the sheet form, the client's files, the inputs, the reading queue) when the page, not
  reading, names other runs than when it was last brought up to date (`useDeliveryRefresh`, `readMark`); not when a flag
  turns. Every answer a decision writes into the cache calls off a read of the same key still on its way (`put`; round
  5: only a read asked for before the decision was sent, and the answer is read once more after one sent since). No
  part of this depends on how long a request takes. Root cause and the evidence: CHANGELOG.
- **The flake, runs.** Before the fix, under a 3-core CPU burner with other agents' work on the 4 CPUs: the whole spec
  once and its corrected-layout test five times on its own (with `beforeAll`): all six passed; the page-level failure
  did not show, but its cause did, deterministically, as an API test (`test_a_reading_that_ends_while_an_answer_is_put_together_leaves_it_saying_reading`,
  which fails on the old code with `running: false` beside version 1's coverage), and the round-3 failure snapshots show
  its signature (the dialog current; the delivery page after the approval, with the old coverage and no "Reading…").
  After the fix, under a 4-core burner: the corrected-layout test on its own 5 of 5 (22.3, 22.3, 22.5, 23.8, 20.2 s).
  The whole spec file five times in one run (`--repeat-each 5`, each with its own project) under a 3-core burner: 55 of
  55 passed; the corrected-layout test 23.3, 25.7, 23.4, 35.4 and 31.5 s. The full e2e suite once on an idle-ish machine:
  118 passed; the 2 that failed were this round's new request assertions (client-confirm counted the delivery page,
  which its study reads; delivery counted a card the work model read again after the signed confirmation), both
  corrected (the first in the assertion, the second in the code: no other card is marked stale) and passed on rerun.
- **§2.1's budget, measured after (copies of the review projects; stub engine, a software fixture).** pKa Save on
  Compound (exampleamide-pbpk-7bb1, another project offering values): the decision and the inputs (round 3: the inputs,
  the offers, the evidence). Accept, Reject, Exclude, "Keep the selected value": the decision and the inputs. Correct and
  "File under this pathway": the decision and the inputs, and the offers only when another project offers values (a
  value newly held can take one away). Add (a value with its source): the inputs and the evidence, and the offers
  likewise. A product confirmed with the sheet form (exampleamide-pbpk-b4e7, Test 10 mg): the confirmation and the
  inputs (round 3: and the client data). **Deviations kept, each read measured as changed by the API's answers:** a
  study confirmed with the sheet form (b4e7, CL-01): the confirmation, the delivery page (a delivery subject reads the
  same source; its card too where it is shown), the inputs and the evidence, and the step bar drawn again once (its
  readiness changed) — 3 reads and a render, followed by 8 prefetches of the sidebar's links; round 3 also read the client data,
  and 25 prefetches followed. The signed confirmation, when its dialog closes: the delivery page, the inputs, the sheet
  form, the client data and the evidence (5; 4 for a product, whose landing leaves the evidence as it was); no other
  card any more (round 3 marked every other card stale, and the work model read again the cards it counts; no other
  card changed in the API's answers, and by the code none can: a card names the sheet form's datasets of its source,
  and a landing makes only the delivery's). *[Corrected in round 5: this holds only with blinding off. With blinding on
  and no plan, the landing puts the study's dataset in the catalog, the MS-01 split can propose S5 for it, and the API
  blinds the study and every product that holds its values (`intake_review.is_blinded`): the product's card changes,
  and this round left it showing the study's values in the same visit. Likewise "a study's confirmation leaves the
  client data as it was" holds only with blinding off. Round 5's sub-heading below says how both are followed now.]*
- **Prefetch.** The step bar's links, its "Waiting on you" links and Inputs' own links are not prefetched; measured, the
  prefetch bought nothing (CHANGELOG). Known gap: the sidebar's four links (Projects, Start from proposal, the library,
  the history), shared by every page, are still prefetched again after each step-bar redraw (8 requests, each a partial
  render of the page up to its loading skeleton). **Owner question:** turn their prefetch off app-wide too, or draw
  Inputs' step bar from a read of `/steps` in the browser (one request in place of the server render and every
  prefetch). Left as is in this round: the sidebar is not Inputs', and the cost comes only when the readiness changes.
- **Round 3's risk (a), the sheet's view.** Read again after the sheet form saves (`SHEET`), so "Read again" in the
  same visit offers to replace the earlier reading whatever the delivery does (client-data-guided checks it with the
  delivery never seen reading). The skeptic's probe (sheet-again.js) on my server: "This sheet was read before" and
  the replace option in the same visit and in a fresh one.
- **Not covered by an e2e:** the marker rule's own case (a reading that starts and ends between two reads of the page)
  is shown at the API by the new test and on the page by the corrected-layout test's runs; no spec holds a read back
  to force it. The one 404 every measured visit logged is the browser's own request for `/favicon.ico`, which the app
  does not serve; nothing of the page.

### Final review fixes round 5: what a decision makes stale (2026-11-16; round 4's blinding regression after a signed confirmation, the card decision and the sheet-form path with it, the race in `put`, the timing failures, the offers' budget; CHANGELOG "Fixed — final review round 5, what a decision makes stale")
- **The rule, as built.** Every answer of the delivery page a decision brings is compared, subject by subject, with the
  page as the decision found it (`changedRows`, lib/freshness.ts: the whole row, so whatever a card shows of it, its
  blinding and why included); the cards of the subjects whose rows changed are read again, at once where they are
  shown or counted (the work model counts every card, so in practice at once), else when next shown; the card the
  decision's own answer wrote is left out (it is current); when a subject's blinding changed, what the delivery's
  blinding also withholds is read again (client data and its sheet views, the sheet form, the documents and their
  figures). Where it applies: `writePage` (the page is the answer), `cardAfter` and the facts form (the page compared
  with what it was when the decision was sent), `writeConfirmed` (with the page as the signature found it), the sheet
  form's saved and read sheets (`SHEET`, `sheetReadAfter`) and the confirmations and dataset decisions that name a
  delivery subject (`readSubjects`). Not applied to the decisions that start a reading (a layout approved, rejected or
  edited, "Read again"): the delivery's end-of-reading refresh reads every card again when the reading ends
  (`useDeliveryRefresh`), and comparing the rows mid-reading would read the cards twice. A second rule follows the
  project's blinding list wherever it changes: the workspace compares the studies the inputs name as blinded
  (`blindedStudies`) on every answer of the inputs, and when they change reads again the client data, the sheet form,
  the evidence, the documents and the delivery page (followed by the first rule).
- **The sheet-form path, read from the code (the skeptic's question).** It can change what is blinded. A sheet form's
  confirmation (`client_api.confirm_review_group` → `_act`) assembles the inputs again (`refresh_inputs`); its study's
  datasets become usable (`inputs.usable_dataset`: a client dataset counts once its study is confirmed) and join the
  study catalog; before a plan the MS-01 split runs on that catalog (`roles.proposed_roles`), and `blinding.external_why`
  lists every study it proposes for S5 or S6. `blinded_sources` then withholds that study's sheets and files
  (client-data's `blinded`, `blinded_sheets`), its sheet-form group, its catalog row, and the delivery's study of that
  name with the products that hold its values. The split is global: confirming one study can move another (measured: a
  study at the lowest oral dose took S2 from the literature's po-10, which went to S5). A rename at confirmation
  (`rename_study`, arms or a link) only renames into the group's own name, and a group whose name is blinded cannot be
  confirmed (409 BLINDED), so a rename alone does not put a dataset under a blinded name. Measured on the API (scratch
  copy of the API tests; five literature studies, the filled template, blinding on): confirming CL-01 made the split
  propose S5 for it; client-data's template file went from `blinded_sheets` [] to ["PK_Summary", "Studies"], the group
  `study:CL-01` and the delivery's CL-01 were blinded, and the inputs listed CL-01 as blinded. Round 4 read the client
  data again after a study's confirmation only when a product's profile was chosen. The second rule above covers it.
- **The race in `put`, as built.** The reads of the page record when each was asked for and when its request went out
  (`useResources` reads wait their turn behind the page's own), and each decision when it was sent (kept with its
  answer). A read of the same answer on its way when the answer is written: asked for before the decision was sent,
  called off (round 4's RLD fix: the answer holds what it was asked for); asked for since and not sent yet, left to land
  (it goes out after the answer); sent since, called off and the answer read once more (the server may have answered it
  before the decision or after it: keeping either could keep the older; the skeptic's suggestion, keeping a read sent
  after the decision, has the same hole when the server answers that read first, so the page reads once more instead).
  Unit checks: `afterAnswer` in e2e/inputs-work.spec.ts.
- **Runs.** The new spec (e2e/inputs-blinded-follow.spec.ts) against round 4's page (04c95b7's build and API on my
  ports): all three tests fail at their same-visit assertion (the product card shows no blinded notice twice; the sheet
  has no "blinded until the plan is signed"); with this round's page all three pass. The affected specs through the
  harness (client-confirm, client-data-guided, client-data, delivery, inputs-a11y, inputs-blinded,
  inputs-blinded-follow, inputs-data-cards, inputs-fill, inputs-owner-job, inputs-sheets-on-arrival,
  inputs-task-first, inputs-todo, inputs-work, inputs-workspace, members, studies-client-sheets, value-reuse): 81 of
  82; the one failure was inputs-blinded's last check finding "35.6" in the audit answer's own timestamp
  (`04:56:35.605…`), not in what it says, now compared with the timestamps left out. delivery.spec's exact request
  lists and client-confirm's hold unchanged. The RLD test under load with this round's `put`: inputs-task-first with
  `--repeat-each 3` under a 3-core CPU burner, 33 of 33 (the corrected-layout test 23.6, 22.3 and 22.3 s).
- **Timing failures (item 3).** The round-4-merged run (e2e-04c95b7.log) had none: 128 of 128. Seen once in round 4,
  both before its request-budget fix was merged: inputs-task-first ':606' at ':691' (Dissolution Test's version 2) and
  ':213' (a loose number still on the raw file's row after the bulk submit). On 04c95b7, inputs-task-first with
  `--repeat-each 3` (each test three times, each repeat on its own project) under a 3-core CPU burner: 33 of 33; again
  under a 4-core burner: 33 of 33 (the corrected-layout test 21.9, 21.4 and 21.9 s); neither reproduced in six loaded
  runs of each test. ':691' is a test-side race, read from
  the code: the test polled until RLD's table was read with version 3 and then read Test's once, but the intake job
  reads the queued files one after the other (`intake_pipeline_jobs._drain`), so Test's reading could still be under
  way; it now polls both. ':213' matches round 4's root cause: with the template's row first in the batch, its refusal
  (409) read the delivery page again, and that read, sent before the raw file's decision, could land after the
  decision's written page and put back the loose number; round 4's `put` calls it off, and round 5's keeps doing so
  (asked for before the decision). A third, seen once in this round's run (Runs above): inputs-blinded's search of the
  audit answer for the withheld "35.6" found it in the answer's own timestamp; the timestamps are left out of the
  search now (inputs-blinded and inputs-blinded-follow then 5 of 5).
- **The offers' budget (item 4).** inputs-todo now seeds another project of the drug with two literature values and
  checks both branches that take an offer away: "File under this pathway" (the decision, the inputs, the offers) and
  Add on a Compound row (the decision, the inputs, the evidence, the offers), each with the offer gone or shrunk after.
- **Deviations and gaps.** (a) In the rare case where blinding changes, the two rules can read the same route twice (a
  signed landing that the split blinds: the delivery's row rule and the inputs' list rule both read the client data,
  the sheet form and the documents); correctness first, the duplicate costs a few reads only then (closed in round 6:
  one rule, each route once). *Corrected in round 6 (the skeptic's finding):* the rule above was not complete. It read
  again only the cards whose delivery rows changed, while the API also withholds by file and by name on cards whose rows
  stay the same: the why of a decision about a file that now holds a blinded study's values (`_decisions`, masked by
  `d.files & hidden_files`), a layout's headers and findings and a source page (by file), and, through the inputs and
  the evidence, a study already in the model (its Studies row, its points) after a card decision blinded it. Probe A2:
  after 230-23 was signed and the split blinded it, unblinded 231-24's "Decisions made on this study" kept "41.7" in the
  same visit while the API answered "••.•". Round 6's sub-heading below records the fix. (b) A decision that
  starts a reading follows its cards at the reading's end, not at once (above). (c) A change by someone else between a
  card decision and its page read is not told apart from the decision's own (the answered card is not read again);
  the next read of that card shows it, as any concurrent change.

### Final review fixes round 5: accessibility, phone and names (2026-11-16; round 4's a11y-cards skeptic: OWN-16 with a file open, A11Y-7's remainder, the demographics form's focus, the records; CHANGELOG "Fixed — final review round 5, accessibility, phone and names")
- **Client files on a phone, a file open.** The phone rules reach only the files table's own rows (`> tbody > tr > td`);
  an open file's tables are no longer held at the kit's 560 px (`:not(.files-detail .table-scroll table, .sheet-grid
  table)`), and on a phone each is a block that scrolls itself if it must. A table in a scroll box of its own inside the
  file (the reading's tables and texts, the sheet grid) keeps its kit width and scrolls in that box, as every values table
  does on a phone: that is the kit's phone answer, kept (its columns are the file's tables' columns). *Corrected in round
  7: since round 6 the reading's tables and texts do not scroll: at 900 px and below each is a block, its parts under
  their column's names (round 6, "Widths", below); only the sheet grid keeps its width and scrolls in its box.* Two extra steps the
  item did not name, found by the same measure: a file's sheet table is a block per sheet on a phone (`sheet-table`, its
  cells named by `data-label`), because even fitting its box it scrolled its state and its button out of sight; and a
  PDF's page lines are read whole on a phone (they were a one-line quote of about 20 letters). Measured at 390 px on
  copies of b4e7 (9 files) and eb47 (3): each file opened, with its reading's tables and texts and its first sheet's
  reader open too, nothing passes the files box but inside a fitting scroll box of its own, no sideways page scroll, no
  clipped line (probes phone.js, phone2.js; the e2e opens each of the 9-file seed's files).
- **Names.** What a value is, for the controls repeated on its row, is `words.valueAbout`: the field in the intake
  vocabulary's words (`layoutFieldText`, which falls back to `fieldLabel`), its time and unit, labels, conditions
  (`conditionsInWords`: an interval in the hours its fields are read in), statistic and file; two that still read alike
  are told apart by their cell (`distinctNames`, `anchorCell`). The words a sentence needs for a field whose label is no
  noun ("fasted or fed state", "share of women (%)") are in `layoutFieldInText`. The spot check's names end "(spot check
  of study …)", so they never equal the same value's Show in its values table. Pagers are named by their table (the kit's
  `TableMore` `of`; the other tables of the app have one per page and keep "Show 8 more"). **Left by design, and now
  asserted to be the only repeats** *(corrected in round 6: on the e2e seed only, and for names without ": ", which the
  scan's pattern alone read; the owner's 7bb1 had three more, recorded and fixed under round 6 below)* (e2e scan of
  Chromium's computed names on Clinical studies and Products with every
  card, values table, page, list of more checks and a spot check open): a values table's sort buttons (Field, Value,
  Time, Read by), under the table's caption, and the spot check's two answers per value ("matches", "does not match"),
  under the value's question (its fieldset's legend names the value). Found by the same scan and fixed: on Products with
  every product card open, "Use as release" (named by its profile), "Confirm its data first" and "Use this profile as the
  release" (by their product).
- **Focus.** A new `asked` on the demographics form re-arms its focus each time the spot check asks for it while it is
  open (the ask's time, from `RequirementRow`'s `start`); the form keeps what was typed (not keyed, so no remount). The
  Pending form on Populations is no longer keyed by what is stated: its openers wait for the card (so it starts from what
  is stated), and it closes on its save. Found while testing, and fixed: `focusSoon` called in the same handler as the
  close could run before React drew the form out, find the opener missing and fall back to the row, whose first control
  was the closing form's population, and the focus then fell to the page (230-23, each time, on a copy of b4e7). A form
  that closes now hands the focus on after the render that removes it (`kit/focus.ts` `useFocusOnClose`), on Populations
  and on the card's required item; other `focusSoon` callers name one target, which it waits for, and are unchanged.
  Measured (probes save.js, cardsave.js on throwaway copies): one focus move, from Save to "Choose the individual…".
- **Records corrected in place:** the round-4 a11y-cards entry (CHANGELOG) and its §5 note above (the names "fixed", the
  phone blocks "fit", the sort buttons and radios "the only repeats", the focus "once per opening").
- **Also fixed, seen in the phone screenshots:** the reading's tables and texts named a table by its ids' words ("table,
  pk individual", "prose"); now `words.regionKindText` ("individual PK table", "text").
- **Left, not changed:** on a phone the reading's tables and texts and the sheet grid scroll sideways inside their own
  box (nothing is cut; their columns are the file's). *Corrected in round 7: since round 6 only the sheet grid does; the
  reading's tables and texts are a block per table at 900 px and below.* The values tables' sort buttons have no table in
  their names (a screen reader says the table they are in); **owner question:** name them too ("Sort the values of … by
  Field")? *(Decided in round 7, left by design and no longer an owner question: each sits in its own table's header,
  see round 7's names and words below.)*
- No API change, no locked file, SME rule (draw size, digest and seed rule, requirement levels, the MS-01 split, which
  studies are blinded) or boundary exception was touched.

### Final review fixes round 5: the formulation lever's edges and the blinded reason everywhere (2026-11-16; round 4's downstream-blinding skeptic; CHANGELOG "Fixed — final review round 5, the formulation lever's edges and the blinded reason everywhere")
- **"add a product's dissolution data" lands on what adds them.** `?tab=formulations&release=<name>`: a product with a
  card opens its release line, whose first control is now "Use this profile as the release", "Confirm its data first" or,
  with no profile that can give a release, "Add its dissolution file…"; a product with no card whose profile is listed
  under the profiles of no product opens that list; any other (a product only the proposal or a study names) opens "Add
  data" on "Formulation and dissolution files…", focused, saying "· the dissolution data of <name>" while it is open
  (kit `Menu`'s `open`; closed, the focus goes to "Add data"). The rows of "The formulation of each solid study" land the
  same way. **Deviation:** the upload has no product field; the dissolution register reads the product from the file,
  so a file that names another product (or the same one spelled otherwise) gives that product's profile, whatever the
  menu said it was for.
- **The way per study (`formulation_way`, `FormulationWayView.each`).** A study that names its formulation: that
  product's profile if one can give a release, else that product's dissolution data, never another product's profile.
  A study that names none (the model then holds no formulation): the profiles that can give a release and are no
  formulation's release already (`_released`: a held formulation's evidence names its profile; a product whose
  formulation the model holds), the confirmed first; else the products here; else a product. The products in the order
  the docstring states: named, then confirmed, then the register's. **Deviation:** the step bar names one lever, the
  first of use a profile, add dissolution data, add a product, choose that a study has, for the studies it settles; a
  study with another way says its own on its row of Products and dissolution and, where its way offers the client, on
  "Ask the client". A study that names a product whose profile was already used as the release of a formulation of
  another name is offered that profile (`use_profile`: used again under the name the study names, it gives the
  formulation the study names), while a study that names none is not offered a profile that is a release already
  (corrected in place in round 6: this note said so, but round 5's code excluded that profile for every study, so such a
  study was told its product "has no dissolution profile that can give a release"; round 6 made the code match). Checked by `test_formulation_way_is_read_for_each_study` with the
  skeptic's seeds (way_edge.py's monkeypatched profiles and confirmations). (Round 6: a study whose own file names its
  product, the usual way, was read here as naming none; see round 6's sub-heading.)
- **The blinded reason everywhere, in one sentence (`blindedWords`).** Populations and individuals' line, a product's card
  head (beside its chip, and its description), and the dataset lines (the Every dataset list's and a study card's: the
  dataset's `blinded_why` on `GET /evidence`, the study's reason on the project's list; round 6: or the delivery's, for a
  study of its name the delivery blinds, which `GET /evidence` did not redact before). The compound is never blinded.
  The Clinical studies list's "because …" and To do's rows stay text (the card itself leads on).
- **The reason leads where it can be changed (`blindedParts`, `BlindedReason`).** "it is entered for external validation
  on its card" is a button to the study's purpose on its delivery card (on a card confirmed with the sheet form, the
  delivery's reading is opened first; e2e on the round-4 template case), where a blinded study's purpose fact offers
  "Change the purpose…" (the value stays withheld; a purpose chosen from the five, with a reason, through `:enter`; the
  API's `PURPOSE_DIFFERS` check unchanged). "the plan places it in …" and "the study split proposes it for …" link to
  Review & sign's "Studies and roles" (`#review-studies`), where a study's role is decided (round 6: only while Review &
  sign can show that section, the inputs ready; round 5 linked whatever their state). "a dataset of it is entered for
  external validation" and "it holds the values of a blinded study" stay text: a dataset's purpose is not changed on the
  page (it is read again with another), and a product's is its study's.
- **The ask follows the way.** To do's formulation item asks for each study whose own way is add a product or add a
  product's dissolution data (`ask`), so wherever the step bar, Review & sign, To do or a study's row offers "ask the
  client" for a study's formulation, "Ask the client" holds the study's line, joined with the delivery's (one line per
  requirement and wording, each study once). A study that names its product is asked for that product's data, on a line
  of its own wording. The delivery's own condition (no delivery product with values) is unchanged: it may still ask for
  a delivery study the inputs' way does not (a profile here), which asks for more, never less.
- **Owner questions:** (1) a curator can now change a blinded study's purpose from the page (the API took it before
  through `:enter`, with the reason on the audit trail), and a purpose changed from external validation unblinds the
  study at once; should that need the reviewer role, as turning blinding on or off does (`PUT /blinding`), or a
  signature? Left as the API had it (a curator, with a reason; round 6: until the owner decides, the page offers it only
  to a person whose roles allow `PUT /blinding`, the API unchanged). (2) round 4's 7bb1 question (231-24 loaded for building,
  entered for external validation on its card) now has a lever on the card; whether to flag the state itself stays open.
- **Checked:** in-process on a copy of the review data, exampleamide-pbpk-7bb1 gives the same lever as round 4 (use a
  profile, Test 10 mg then Brand 10 mg, `ready` false) with each of its two tablet studies' own, and 231-24's group says
  "it is entered for external validation on its card"; the skeptic's way_edge.py now gives Test 10 mg's dissolution data
  for a study naming Test 10 mg, and the named product first. In a browser (e2e, stub engine): the owner-job's third
  test, inputs-blinded's four, blinding. A software fixture, not PBPK evidence.
- **Records corrected in place:** round 4's CHANGELOG entry and §5 sub-heading (the landing of a product with no card,
  the order of the products, the reason "wherever" a study is withheld, the ask's condition as what was left, the dataset
  line as not built).
- No locked file, SME rule (which studies are blinded, requirement levels, the spot check, the MS-01 split) or boundary
  exception was touched. API changes are additive (`FormulationWayView.each`; `blinded_why` on a blinded dataset).

### Final review fixes round 6: what a newly blinded study withholds elsewhere (2026-11-16; round 5's blinding-fresh skeptic: the follow rule complete and once per route, one source for a study's withheld values, no signature offered on a blinded card, the records; CHANGELOG "Fixed — final review round 6, what a newly blinded study withholds elsewhere")
- **The rule, as built (`followBlinding`, components/delivery/writes.ts).** One place decides what a change of the
  project's blinding reads, either way, whichever answer shows it: a delivery row whose blinding or reason changed
  (`followRows`, after every answer of the delivery page a decision brings, as in round 5) or the studies the inputs
  say are blinded (`blindingChanged`, the workspace's comparison on every answer of the inputs). It reads `BLINDING`:
  the delivery page, every card of the project and its spot check, the layout views (`/delivery/mappings/{id}`), the
  source view (`/delivery/source`), the inputs, the evidence, the client data and its sheet views, the sheet form, the
  documents, their pages and their figures; at once where shown or counted (the work model counts every card), else
  when next shown; only the project's answers. Without a blinding change `followRows` reads the changed rows' cards only,
  as before, and nothing else reads more.
- **Once per route (round 5's gap a).** Reads record the moment they were asked in, and `put` the moment it wrote an
  answer (`moment()`, lib/hooks.ts: one per task, so a change's answer and every read it sends in the same go share it).
  `readAgain(…, since)` leaves out what was read or written in `since` or later, which holds the change. `since` is the
  moment the decision was answered in (the delivery path; the facts form's first entry), or the moment the inputs that
  show the change were read in (the inputs path, `readMoment`). A second answer that shows the same change, read by the
  last following of it or by the decision's own reads, is followed from that following's moment (`followFrom`,
  lib/freshness.ts; unit checks in e2e/inputs-work.spec.ts), so when both paths see one change (a signed landing the split
  blinds), each route is read once (e2e: the signed-landing test counts the reads after Done). **Deviation:** the task
  said to remove the unused `askedAt`; it is removed, and `readMoment` (by key, the moment rather than the precise time)
  is what the inputs path needs.
- **"Change the purpose…" folded in.** A purpose change on a blinded card changes its row's blinding, so `cardAfter`'s
  page read brings it to the rule; `PURPOSE_READS` and `CardDecide`'s `reads` are removed. inputs-blinded's purpose test
  is unchanged and passes.
- **One source for a study's withheld values (item 2).** Why they disagreed: `GET /evidence` redacted by
  `deps.blinded_why` (the project's list, `blinding.listed_why`), while the sheet form's line comes from
  `deps.blinded_sources` (the list and the delivery's rule, matched by name). On 7bb1 the delivery blinds 231-24 (its
  card's purpose) and the list is empty, so the list-only redaction showed its points. `BlindedSources` now carries the
  list (`listed`) and answers `withholds(study_id)` / `study_why(study_id)`: the list's id, else a study of the same name
  in `names` (the list's under another spelling, or one the delivery blinds). Used by `GET /evidence` (points, reported
  PK, `blinded_why`, `blinding.blinded`), the client review's dataset items, `GET /inputs` (Studies rows' `blinded`, the
  catalog's profiles), Review & sign's studies, `GET /studies` (the Run page), the artifact view and history
  (`redact`, `hidden_paths`, only for datasets and the catalog) and the reveal's audit entry. It applies the existing
  set: the list's rule, the delivery's rule and the MS-01 split are unchanged (on 7bb1 in-process: the list empty, the
  delivery blinding 231-24 and 230-25, as before; only 231-24's dataset is newly redacted). `/blinding`'s `blinded` stays
  the list (it describes the setting).
- **No signature offered on a blinded card (item 3).** In place of "Confirm and sign…" (and "Confirm again…", "Finish
  the loading…"), a blinded card says "Signing waits until the plan is signed, because …" (`signWaitsWords`); the API's
  409 `BLINDED` is unchanged. The card's withheld line names its kind ("this product").
- **Runs.** pytest: the new test fails on 8f43eb5's API at the evidence (`blinded` missing) and passes now;
  tests/architecture and the API suites touched (test_delivery_api, test_client_api, test_evidence_api, test_inputs_api,
  test_plan_api, test_project_api, test_read_api, packages/project-model): 1258 passed; `make test`: 3173 passed, the
  same 15 failures as 8f43eb5's (services/orchestrator and data-intake, the environment's). e2e (stub engine, ports
  8061/3061): the whole suite once, 146 of 146 (10.3 min). The two new follow tests against round 5's web (8f43eb5's
  components and lib, this round's API): both fail at their same-visit assertions (231-24's decisions without "••.•";
  no "blinded" chip on the landed study's Studies row). The 7bb1 copy in a browser (this round's build, an API on a copy
  of the review data): 231-24's card shows its dataset line "blinded until the plan is signed" with the reason and no
  "Show the points" beside the sheet form's withheld line, and its row in the model says "blinded". A software fixture,
  not PBPK evidence.
- **Gaps and owner questions.** (a) A decision that starts a reading (a layout approved, rejected or edited; Read again)
  still follows at the reading's end (round 5's gap b). (b) A change another person makes is seen at the next read, and
  one made between a decision and its follow-up read is taken as the decision's (round 5's gap c). (c) A sheet read with
  the sheet form for external validation whose study has no delivery subject and is not in the catalog yet (a proposed
  dataset only) is not seen by either path; its own decision reads the client data and the sheet form, not the evidence
  (round 5's gap d, unchanged). (d) Owner question, still open from round 4: on 7bb1, 231-24 is in the model for model
  building while its card says external validation (a state the sheet form's `PURPOSE_DIFFERS` now prevents); its values
  are withheld everywhere now, but the state itself is not flagged. (e) The datasets' write answers (`:study`,
  `:overlay`, `datasets`, `:digitize`) return the dataset as stored to the person who made the change, blinded or not, as
  before.
- No locked file, SME rule (which studies are blinded, requirement levels, the spot check, the MS-01 split) or boundary
  exception was touched. No API contract change (the same fields; `study_rows` takes a rule).

### Final review fixes round 6: the product a study's own file names, and the plan link (2026-11-16; round 5's downstream-why skeptic; CHANGELOG "Fixed — final review round 6, the product a study's own file names, and the plan link")
- **A study whose own file names its product (`formulation_way.file_products`).** The client template's Studies.product
  (the sheet form keeps its rows) and the delivery's values of a study that name a product are read by the study's id as
  the readiness check says it (`<study>-<arm>` for an arm's row or value, as its dataset is named; a value of the whole
  study counts for each of its arms; ids compared by `ledger_entities.label_key`). Such a study is one that names its
  product: that product's profile, else its dissolution data, never another product's profile; the client is asked for
  that product's data ("The formulation or dissolution data of Test 10 mg, the product the study used — study CL-02",
  the line carrying the product). **Deviations:** (1) both paths are read whether or not the file's study or values are
  confirmed: the file names the product either way, and the study is in the model through one of them. (2) A study whose
  files name two products (the sheet form one, the delivery another, or two arms' products for a study-level dataset) is
  settled by either one's profile, the first named first, and the client is asked for "Test 10 mg or Brand 10 mg"; the
  disagreement itself is not flagged here (the client review's conflicts are where names are reconciled). (3) A name
  no product here has is kept as the study's (its dissolution data are added, or the client asked), spelled as the file
  spells it; a name that matches a card's or a profile's product (`_key`: case, spacing, a leading "Product") is said as
  that product is named.
- **Owner question (science, the model building):** the readiness check and the CPF read only the study record, which
  carries no product from the file. While the model holds exactly one formulation, a tablet study that names none in its
  record uses it (`resolve_formulation_name`, with a note): a study whose file names Test 10 mg is modelled with Brand 10
  mg's release if Brand 10 mg's is the only formulation, with no problem raised. The page no longer leads there, but
  nothing stops it (a person may use Brand 10 mg's profile from its own card for another reason). Should the assembly
  give such a study the formulation made from its named product's profile (or name the product as its formulation, so
  the check says it is missing)? That changes what is built: left for the owner. The same holds for a study the delivery
  names a product for but that a person's formulation choice names otherwise (the person's choice wins, as today).
- **"Ask the client": one anchor per line.** `askAt`: `todo-ask-REQ-form.release~<product>` for a named product's line,
  `todo-ask-REQ-form.release` for the line of the studies that name none, the delivery's lines by their requirement as
  before (a per-product line keeps its `@<product>`). The step bar's, Review & sign's and To do's "ask the client" lands
  on the line of the study whose product the link opens first (`formulationWays`); a study's row on its own; a product
  card's on its product's line, else the delivery's line of that product, else the line of the studies that name none
  (after a second), else the group.
- **`StudyWay.ready`** follows the first product listed (round 5 took it from the first profile, possibly of no product).
- **The plan's part of a blinded reason (`BlindedReason`, `ReachContext`).** Linked to `/plan#review-studies` only while
  Review & sign can show "Studies and roles": the inputs ready and checked since they last changed (the page's GET
  /inputs readiness; the API's `inputs_ready`, and GET /plan then makes the default plan if there is none). Otherwise said,
  with "(its role is decided on Review & sign, which opens once the inputs are ready: what they still wait on)", the link
  focusing the step bar's "Waiting on you" over To do (To do's model checks do not repeat a check a To do group lists,
  so they may show nothing open). **Deviation:** "the steps state" in the finding is read from the page's own readiness,
  which follows every change on the page; the server-drawn step bar is the same state at load.
- **A blinded product's card** says why once, on its head, naming the study (`intake_review.held_why`, also the sheet
  form's group reason in `blinded_sources`); its body says what is withheld, never "this study is blinded". A study card
  keeps the reason on its withheld line (its head is the list row).
- **Owner question (open, recorded in round 5): who may unblind a study by changing its purpose.** Until the owner
  decides, the page offers "Change the purpose…" only to a person whose roles allow `PUT /blinding` (modeler-reviewer,
  `GET /me` read once for the visit with the page; `BLINDING_ROLES`); to anyone else the purpose says "it blinds the
  study; a reviewer (the MIDD lead) can change it", where the reason's link lands. **The API is unchanged:** `:enter` on
  `intended_use` still takes a Writer's change with a reason, so a Writer can still unblind a study through the API
  itself; closing that needs a role check on `:enter` for a blinded study's purpose, or a signature (the owner's call).
  The e2e cannot sign in as a Writer (the DEV sign-in holds every role, `auth.py` is locked), so it gives the page a
  curator's roles through `GET /me` (Playwright `page.route`).
- **Corrected finding:** the downloadable client request (`request.xlsx`) is built from the data plan's client items
  (`requirements.client_request`), not from "Ask the client", so it never held "(no file names the product)": its
  formulation line is the data plan's "Release model of the product (dissolution)" (product column empty while the
  proposal names none). **Gap / owner question:** the download does not list what "Ask the client" lists from the
  delivery and the inputs (each study's or product's line); should it?
- **Gap (unchanged, rules):** the delivery's per-product release item for a product whose dosage form only its study
  states (the study's formulation, not the product's dosage_form or release) is "not applicable"
  (`study_requirements._is_solid`, as `requirements.derive` decides it), so the delivery asks nothing for Test 10 mg;
  the inputs' line asks for it. Changing which items apply is a requirement-level (SME) decision: not changed.
- **Checked:** pytest `test_client_api.py` (the API on a template naming Test 10 mg beside Brand 10 mg's confirmed
  profile; `file_products` on both paths and each case; `ready`; the named profile used again; `held_why`); the skeptic's
  way_edge5.py now gives use_profile Test 10 mg for case 1 and `ready` false for case 2; in-process against a live API
  (probes B and D: add_dissolution Test 10 mg, named, the named ask line with its product); `inputs-work.spec.ts` units;
  e2e `inputs-owner-job` (the fourth test), `inputs-blinded` (five tests) and the specs that cover the changed components.
  A software fixture on the stub engine, not PBPK evidence.
- **Records corrected in place:** round 5's §5 deviation on a named study's reused profile, its bullet on the plan link
  and its owner question (1); round 5's CHANGELOG entry (each row "says that study's own way"; the plan link; the purpose).
- No locked file, SME rule (which studies are blinded, requirement levels, the spot check, the MS-01 split), ruleset or
  boundary exception was touched. No API contract change (untyped `ask` lines carry their product; a blinded product's
  `blinded_why` names its study).

### Final review fixes round 6: names and words on the owner's own project (2026-11-16; round 5's a11y-phone skeptic: the repeats on 7bb1, the raw field ids and kinds, the widths, the records; CHANGELOG "Fixed — final review round 6, names and words on the owner's own project")
- **Scanned where the owner works, not only on the seed.** Every area of Inputs on copies of all eight review projects
  (`exampleamide-pbpk` and its copies b4e7, 7bb1, 39c9; `clientamide-pbpk` and eb47, 1acd, 4701), every card, values
  table, list of more checks and dataset's points open, every file of Client files open with its tables and texts: the
  names Chromium computes and the text shown, against dotted and snake-case ids, check codes, raw table kinds, confirmation
  and dataset ids and engine words (probe `r6names/pw/scan.js`, POSTs aborted). **The scan pattern itself was wrong:**
  Chromium's ARIA snapshot is YAML and quotes a line whose name holds ": " (`- 'button "Accept as is: …"'`), and the
  pattern of round 5's probes and of its e2e scan read only unquoted lines, so every name with a colon (most of round 5's
  names) went unchecked. Both read them now.
- **Repeats on 7bb1.** (a) 230-23's two observed datasets (the parent, six subjects and their mean ± SD; the metabolite
  Exampleamide-M1, its mean ± SE; both from messy-delivery.xlsx, landed by one signed confirmation, whose id was their
  locator) now say what each holds and where it starts in the sheet, visibly and in their names (`words.datasetHolds`,
  `datasetSource`, `datasetPlace`, `datasetNames`): "Exampleamide in plasma, 6 subjects and their arithmetic mean ± SD ·
  messy-delivery.xlsx, sheet Fasting from row 4" and "Exampleamide-M1 in plasma, arithmetic mean ± SE · …, sheet Fasting
  from row 22"; the confirmation's id ("Delivery confirmation cf-33") and a spreadsheet's page ("p.1", "p.6") are never
  said. The place is read from the dataset's quote's row prefix (`[Fasting row 4]`, the library's row line), never its
  cells. Every dataset control repeated per line (Show or Hide the points, Leave it out…, its reason and button, the reveal,
  the overlay check) carries that name, on a study's card and in "Other observed data". (b) The studies table's individual
  button ("not stated" twice) is named by its study and says where it leads ("not stated: the individual of study 230-23,
  on Populations and individuals") and lands on that study's row there, its first field focused (or, shared with other
  studies, its "Change the individual of …" button). (c) The formulation-way button of Products ("confirm a product's
  dissolution data, then use its profile as its release") is now named with its product (": Test 10 mg"); on 7bb1 both
  rows (230-23, 231-24) lead to the same place, Test 10 mg's card at its release (`openRelease` of the study's own way,
  whose first product is Test 10 mg for both), so the two names are alike by design; rows whose ways name other products
  now differ.
- **Raw field ids and kinds.** A check's field and, for a unit check, its unit are sent apart (`CheckResult.field`,
  `.unit`, set where the message is made for the field-led checks: DUPLICATE_TIME, TIMES_NOT_INCREASING,
  STATISTIC_MISSING, SPREAD_KIND_MISSING, NEGATIVE_VALUE, ABOVE_RANGE, UNIT_MISSING, UNIT_NOT_IN_TABLES, UNIT_NOT_CHECKED,
  MARKED_VALUE, LANDING_FIELD_MISSING, NCA_MISMATCH; `DeliveryCheck.field`, `.unit`, null for a blinded subject as its
  message is), and the page says them in the intake vocabulary's words (`words.checkText`): "Cmax (PK parameter): values
  in “ng/mL”; …", "Particle size d50 (µm): …", "the study record needs the number of subjects". The message itself is
  unchanged (it stays the API's record). Also: "looks like an individual PK table" (ReadTable, `tableKindText`); a
  dissolution profile's conditions in `conditionsInWords`; the reported PK of a dataset ("half-life", "AUC last", never
  `t_half`); a series' statistic and a study's route, dosage form and food state in words ("IR tablet", never
  `ir_tablet`); "kept in the ledger" → "kept with the delivery" in a check; a dotted field the landing holds back ("Excretion
  (amount excreted)"); an arm's missing facts ("arm Cohort 1: the number of subjects, the route and what the study is for
  are not stated", never `n`, `intended_use`); the template's problems ("sheet PK_Summary, cell F7: …", "arithmetic mean",
  never `PK_Summary!F7`, `arithmetic_mean`); a template's numbered column as a label ("vessel 1", never "vessel vessel_1");
  a table's name keeps "PK" ("the PK summary table", never "the pK summary table", `words.lowerFirst`); a sheet's kind in
  the tables' words ("individual PK", never "PK, individual"); a dataset's origin ("digitized figure", "OSP library");
  the confirm dialog's "It cannot be signed yet" (it said "3 failed checks: ABOVE_RANGE, LANDING_FIELD_MISSING, …" and
  the loading's problem with `n`, `intended_use`; now `shared.blockerDetail`: each failed check by what it says, a blinded
  subject's by their count only, the facts not stated by their reasons; and `landingText`). *Corrected in round 7: this
  held for the field the API names at a message's start, not for every id: the sweep's patterns did not match an id
  with a capital ("AUC_last"), a one-word id ("ph") or a role code ("TEST"), and it read the card's check row but not To
  do or the card's to-do list, which still built a check's line from the raw message. The owner's 7bb1 still showed a
  dataset's flag "reported AUC_last unit 'ng*h/mL' not comparable …" and "no apparatus, medium, ph stated"; b4e7 and 39c9
  "ph '6.8' is taken from the file name" and "Test 10 mg · TEST · …"; To do "concentration: values above the range…".
  Fixed and recorded under round 7's names and words below.*
- **Left by design, after the sweep** (all eight projects, every area, names with ": " read): a values table's sort
  buttons (Field, Value, Time, Read by), under the table's caption (round 5's owner question stands: name them with their
  table? *Decided in round 7: no, left by design; see round 7 below*); the spot check's two answers per value (not drawn in this sweep; round 5's e2e asserts them); the
  formulation-way button on 7bb1 (one target, above); and one id on purpose, the signed record's fingerprint under "Confirm
  and sign" ("fingerprint of the signed record 5a1b4ce0f709", was "record 5a1b…"): it is what a reviewer matches with the
  audit trail (21 CFR Part 11). A file's own words stay as written and quoted: a sheet's name (`PK_Summary`), a note's text
  (“particle_size_d10_um”, “vessel_1”, the template's header cells).
- **Widths.** A PDF's page lines wrap in their place at every width (the one-line ellipsis applied above 600 px). The
  reading's tables and texts are a block per table, its parts under their column's names, at 900 px and below (on a phone
  the State chip and messy-delivery.xlsx's "waits for approval" sat half off the screen inside the table's own scroll
  box; at 768 px its last column did); above, it fits. Two more, found by the same measure: the files table needs 626 px,
  so from 601 px its box scrolled sideways with no file open (its rows are blocks up to 700 px now, were 600); and at 768
  px a sheet's state chip and last cell kept their line ("blinded until the plan is signed") and set messy-delivery.xlsx's
  open file 47 px wider than its box on 7bb1 (they wrap at 900 px and below). Measured (probes `widths.js`, `closed.js`)
  at 360, 390, 601, 700, 768, 1024 and 1440 px on copies of 7bb1 and b4e7, every file open with its tables and texts: no
  box or page scrolls sideways, every state chip in view, no line cut. **Deviation:** the item named a phone; the stacking
  reaches 900 px, because at 768 px the table still scrolled sideways in its box (by 9 to 68 px on b4e7). A tablet's page
  is long with every file's tables and texts stacked; accepted for no sideways scrolling.
- **Found, not mine, left for the blinding group and the owner:** `GET /evidence` keeps a blinded dataset's `quote`
  (`blinding.redact_dataset` withholds its series and reported values only), and a delivery-landed dataset's quote is
  its first row verbatim ("[Fed row 4] A4=101 | B4=BLQ | C4=5.2 …"), values included. The page never shows a quote (round 6
  reads only its "[sheet row n]" prefix), but the API serves it. Not changed here: it is outside this group's items, and
  `/evidence`'s redaction is the blinding work's; **owner question:** withhold a blinded dataset's quote (and its note) too?
- No locked file, SME rule (the spot check's draw size, digest and seed rule, requirement levels, the MS-01 split, which
  studies are blinded) or boundary exception was touched. The API change is additive (`DeliveryCheck.field`, `.unit`;
  snapshot and web types refreshed).

### Final review fixes round 7: raw words in checks, notes and labels (2026-11-16; round 6's names-words skeptic, on the owner's 7bb1 and on b4e7, 39c9 and exampleamide-pbpk; CHANGELOG "Fixed — final review round 7, raw words in checks, notes and labels")
- **Where each id is now said in words.** (a) A dataset's flags: the page words each flag the dataset check writes
  (`words.datasetFlagText`). **Deviation:** the item offered the API sending the parts apart or the message written in
  words where it is made; the flags are a stored record (`ObservedDataset.flags`) that other code matches by prefix
  (`cross_file:`, `nca_mismatch`), and 7bb1's is stored, so the page words them by their fixed shape, and an unknown flag
  has its field ids worded. (b) "ph" and the other condition ids: written in words where the messages are made
  (`modeler_intake.fields.CONDITION_WORDS`, `condition_text`; `intake_checks`, `intake_landing`), and the page words a
  message written before (`fieldIdsInWords`, never inside a quote). Checks are made on read, so 7bb1 and exampleamide-pbpk
  show "no apparatus, medium or pH stated", "pH 6.8" at once; a check's id never depends on its message. (c) The sheet
  form's note: by its field's label where it is made (`sheet_form`), and `words.sheetNoteText` for the notes kept with a
  reading (b4e7 and 39c9 keep "ph '6.8' …"), on the sheet-form card, the sheet reader and a draft's notes. (d) To do and a
  card's to-do list: `checkText` on the field and unit the API sends; a disagreement's field by `layoutFieldInText`. (e)
  N_MISSING carries `field` and its article ("an arithmetic mean"); the spreads' check likewise. (f) A profile's role code:
  `words.profileText` (the role in words, or left out where the product's name says it; the label itself stays the
  register's, `ProfileKey.label`, stored with the profile and naming it in the problems), on the sheet form's items and
  differences, the chart, "Use as release" and the formulation field, the dissolution notes; a link row's facts by
  `factWords` ("test product", "strength 50 mg"). (g) The agents' hover: words on a project's pages, the setting's name
  in the admin console and in the server's log at its start (`agent_jobs.log_agents_status`; a log-once set was tried and
  refused by `tests/architecture/test_process_state.py`, module state being per process, so the log is at start).
- **Science-adjacent, beyond the words:** the dataset check read an AUC unit only as "ng/mL*h" and flagged "ng*h/mL", the
  delivery's own unit, as not comparable, so 230-23's reported AUC was never compared with its profile's NCA while the
  intake check (`_factor`) did compare it. One reading now (`datasets.auc_unit_parts`, used by both); `NCA_TOLERANCE` [SME]
  is unchanged. A dataset checked before keeps its stored flag until it is checked again (its next revision or landing):
  on 7bb1, 230-23's parent still says, in words, that its AUC was not compared. **Owner question:** re-check stored
  datasets' flags on read, or leave each record as it was checked?
- **Found by this round's sweep and fixed:** a file's reason for its kind named its cell by a raw locator ("Diss pH
  6.8!D1", where `file_tags` writes it and `tagWhyText` for a reason kept before); a dataset's "not in the data plan"
  hover named its id (`unpromisedText`); another project's offered values said "elim (…)" (`idWords`); a card's "checks to
  decide" hover named a layout's id, "mapping mp-9c55440c25bd v1" (`engineWords`).
- **Cancel.** Each "Leave it out…" form's Cancel is named by its dataset ("Cancel: the dataset of …"), as its reason and
  button are; `delivery.spec.ts` opens both of 230-23's forms on the seed and asserts the six names apart.
- **Left by design, decided here (no longer an owner question):** a values table's sort buttons (Field, Value, Time, Read
  by) keep their one-word names. Each is a column header's button inside its own table, under the table's caption (the
  table names its subject and file), so a screen reader announces the table and the column with it: the purpose is
  determined by its context (WCAG 2.4.6 with 1.3.1, as "Sort" buttons in a data grid's header are), and naming each with
  its table would repeat the caption at every column. Also left, as before: the spot check's two answers per value; the
  formulation-way button on 7bb1 (one target); the signed record's fingerprint and, in a hover, the intake rules' digest
  (both the audit trail's match, 21 CFR Part 11); a client's own words as written (a sheet named "PK_Summary", quoted
  cells and headers). Seen, not ids and not changed: the reading's stage hovers on Client files ("0 by cache, 1 by rule,
  0 left for the table mapper") use the reading's own stage words.
- **The scan.** The e2e scan (`inputs-a11y.spec.ts`) and the probe (`r7words/pw/scan.js`, POSTs aborted) look wider:
  any id with an underscore and a lower-case part (a client's "PK_Summary" passes: its part after "_" starts with a
  capital), any dotted model input, "ph", a role code in capitals, a dataset's, a layout's or a hash's id, a check code,
  an environment variable, "a" before a vowel, a raw locator; names, visible text and hover texts (`title`); every
  dataset's points and its "Leave it out…" form open. **What it found on the review copies** (all eight, every area, every
  card, values table, list of more checks, dataset and form open, every file of Client files open with its tables and
  texts), after this round's fixes: no raw id, role code, "ph", locator or variable; what remains is by design (the
  fingerprint, the rules' digest, the client's "PK_Summary"), and the only repeated names are the sort buttons and 7bb1's
  two formulation-way buttons. Before the fixes, on the same copies: the items above, plus the four found by the sweep.
  On the e2e seeds the wider scan passes (Clinical studies, Products, To do, Compound, Populations, Settings, Client files
  with every file open).
- **Records corrected in place:** round 5's two notes on the reading's tables and texts on a phone (only the sheet grid
  scrolls since round 6); round 6's "No field's id on the page", "the page speaks one vocabulary", the sweep and the e2e's
  "no raw id" (CHANGELOG and §5), narrowed to the check row's leading field and to the patterns the sweep had.
- No API schema change (messages' words only); no locked file, SME rule (the spot check's draw size, digest and seed rule,
  requirement levels, the MS-01 split, which studies are blinded, `NCA_TOLERANCE`) or boundary exception was touched.
