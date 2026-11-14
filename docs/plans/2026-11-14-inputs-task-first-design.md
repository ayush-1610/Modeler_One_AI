# Inputs, task-first: the full design text (2026-11-14)

The winning design of three, as its author wrote it. `docs/plans/2026-11-14-inputs-task-first.md` governs where the
two differ (the judges' grafts and the lead's decisions).

## Principle

The page first answers "what must I do next, and where?". Everything else is reference, shown quietly. Six rules follow, and every component below obeys them.
(1) One list of work. A single model (`lib/inputsWork.ts`) is built from both intake pipelines, the /inputs to-do list and readiness. It feeds the "To do" tab, the status line, the tab counts, each area's "Open here" strip, each card's blockers and each file's "Still needs you" column, so every count agrees.
(2) One home per decision. A decision is made with one component and one set of words. When the To do list shows it inline (for example a disagreement), it renders that same component bound to the same server state, never a second variant.
(3) One card per study or product, and one confirm path per card. The card is chosen by a deterministic join of Delivery subjects and legacy client-review groups (by dataset, then label, then file). The path follows `confirm_on`: Delivery gives "Confirm and sign", the template or sheet form gives "Confirm". The other reader's view of the same data is folded into the card as read-only "How the files were read", with its aliases shown ("also read as 230-23-REF").
(4) One row and one status per file, in "Client files". No other file list exists.
(5) Four status words only: Missing, To confirm, To decide, Done. Amber means "your decision is needed here", at most one mark per card. Counts are neutral numerals.
(6) Nothing a person can do today becomes impossible. Rare or advanced actions move into a ⋯ menu or an "Edit" disclosure instead of being deleted. Reasons stay required where the audit trail needs them, but a bulk action takes one reason, offered as suggestion chips the person still confirms. The Part 11 step-up signature and blinding are unchanged.

## Page outline

## Frame: the same on every tab (area bar at about y=400 at 1440×900; today it sits at y=6120)

1. **Head.** Uses `Hero` through `PageShell` at compact size, about 170 px tall.
   - Eyebrow "Step 2 of 4", title "Inputs".
   - Lede, one line: "Fill in what the model needs and confirm the client's data."
   - One secondary action, an **"Add data ▾"** menu. Items: Upload client files… · Download the client-data template · Digitize a figure · Type a table in · Find observed data (AI; hidden when AI is off) · Search the sources and the literature · Take the published OSP model's values.
   - Removed:
     - the source-selection lede and the `hero-note` (InputsWorkspace.tsx:271-272), which move to To do › Model checks;
     - the primary "Search the sources and the literature" button, which moves to the Compound header with its testid `ask-literature`.
2. **Step bar** (`Stepper`).
   - Static on Inputs, no longer sticky (design.css:102).
   - Its "Waiting on you" line goes through the check-label map: "6 compound values missing · no observed data confirmed yet · the model can't be built yet".
3. **Status line** `inputs-status`, one row of about 44 px.
   - Content: "9 client files · [6 Missing] [12 To confirm] [19 To decide] · 3 done · In the model: 0 studies · 0 formulations · 14 compound values".
   - Each bracketed count is a button that opens To do filtered to that word. `to-confirm` (with aria-pressed) and `to-confirm-count` stay on the To confirm button.
   - Right end: **"Next: Check 10 table layouts →"**. This is the page's single primary button; it focuses the first open row.
   - When AI is off, a muted "AI reading is off" note appears.
   - aria-live is set only on a short count span.
4. **Area bar** `area-bar`: kit `Tabs`, horizontal.
   - Stickiness: sticky at top 0 (top 72 px on a phone, under the header), opaque `--bg`, 1 px hairline.
   - Tabs: **To do 31 · Compound 6 · Products and dissolution 5 · Clinical studies 12 · Populations and individuals 5 · Simulation settings · Client files 9**. Counts are neutral numerals, with screen-reader text "31 to do".
   - Below 900 px the bar becomes a one-row horizontally scrolling strip and never wraps.
   - The page opens on To do while anything is open, otherwise on Compound. `?tab=` still selects a tab, and now also accepts `todo` and `files`.
   - Testids `tab-compound|formulations|studies|individuals|settings` are kept; `tab-todo` and `tab-files` are new.
5. **Review bar.** When the person arrives from a To do row, a slim bar sits under the area bar: "From To do · 4 of 12 · ‹ Previous · Next › · Back to To do".

## Tab "To do" (the default), root `still-missing`

The head is an h2, **"What needs you"**, with the line "Start at the top: each group unblocks the ones below." Controls: filter chips All · Missing · To confirm · To decide; an Area select; and "Show done".

Groups appear in this fixed order, and a group with no items is not rendered. The first group starts open. The others show their header and first 3 rows plus "Show n more". Each row is one line that expands in place, with one row open per group.

0. **Ready to confirm now (n).** Lists the subjects with nothing open, for example (exampleamide) "Study CL-01 · client-template-filled.xlsx · Ready". The button **Open** goes to the card in its area. These quick wins come first because they put studies into the model.
1. **Check how tables are read (10)**, To decide. Lede: "A table's layout decides which of its numbers become values. Until a person approves it, they can't be confirmed with a signature."
   - One row per layout (mapping_id), naming every file that uses it: "Individual PK table · 230-23 Fasting Reference.xlsx, Sheet1 A4:M12 · and 230-23 Fasting Test.xlsx · suggested by the template rules · 152 values wait on it".
   - Button **Check layout** opens `MappingReview` in queue mode at that row's **version**, with Previous / Next / "Approve and next".
   - Excretion and product-attribute layouts carry a neutral tag "kept, not used by the model".
   - Batch action: "Approve the 2 'not data' readings (README sheets already set aside) · reason · Approve".
   - Rows are ordered by how many values they block. Testids: `todo-layout-<mapping_id>`; `delivery-mapping-<mapping_id>` is kept on the same row.
2. **Link values to a study or product (6 files · 366 values)**, To decide. Rendered by `LinkTable`, which replaces Unassigned.tsx.
   - One row per **file**, with its table and its facts merged.
   - Columns: ☐ | File | Holds ("individual PK table, 76 values; dose 50 mg, fasted, LLOQ 0.5 ng/mL") | Study · arm | Product · batch | Show values.
   - The Study and arm cells are pre-filled and marked "suggested". Sources of a suggestion, in order: the region caption ("Study 230-23 … Reference"), the file name, and the name the sheet form gave the same file ("230-23-REF").
   - A sticky **BulkBar** reads "2 files selected · Reason [file name and table title say 230-23] · Link". It sends one `values:assign` per destination, with all targets in it.
   - "Show 79 values" opens a paged value table.
   - When the sheet form named the file, a note reads "Also read by the sheet form as Study 230-23-REF → open that card".
3. **Numbers not read (72 in 5 tables · 5 loose · 1 text)**, To decide.
   - One row per file. Expanded, it shows the silent cells (listed once the API sends them), the loose numbers grouped by pattern ("12 column headers vessel_1…vessel_12 · Dissolution!H1:S1"), and unread text ("page 1, text · not read: AI reading is off").
   - Checkboxes per item and per group, plus "select all". BulkBar: "Mark 45 selected as not data · reason [a column header, not a value] · Apply". It sends one `regions:exclude` per file and scope.
   - Unread table regions get "Read this table…".
4. **Fill in what's missing**, Missing. One sub-row per subject.
   - **Compound** · 6 missing: a `MissingValues` batch table (Parameter | Value | Unit | Quote) with one shared source (type, title, DOI or URL). pKa and the elimination pathway use their existing pKa and process choices.
   - **Study 230-23** · route, number of subjects, purpose: a typed `FactsForm` with one reason.
   - **CL-01** · analyte and matrix not stated: **State it…**.
   - **Exampleamide IR tablet** · dissolution apparatus not stated (2 runs).
   - **Demographics** · 5 studies: Enter them… or Ask the client.
   - Also here: the regimen of a multiple-dose study, and the formulation of the tablet studies.
5. **Settle disagreements**, To decide.
   - Sheet-form issues (Conflict / Differs / Question / Same study? / Same product? / Same batch?).
   - Delivery ConflictRow and LinkRow, but only for subjects on the Delivery path.
   - Compound items: 2-fold conflicts, pKa acid or base, filed under the wrong parameter, "check this value" (held), unit to convert, which process.
   - Each row is the same component the card renders.
6. **Confirm the client's data (n)**, To confirm.
   - One row per unified subject not yet confirmed: kind · name · aliases · area · readiness ("Ready" / "3 things first: …", each a jump link / "Waits for the delivery clean-up") · path ("Confirm and sign" or "Confirm") · **Open**.
   - Open goes to the card, and the review bar appears.
   - Testid `todo-confirm-<key>`; `missing-confirm-<group id>` is kept for legacy groups.
7. **Ask the client (9)**.
   - One list fed by both pipelines and grouped by requirement: "Demographics (age, sex, population, weight) · CL-01, 230-23, 231-24, 230-25, 230-26 · needed for every model".
   - Buttons: [Mark as asked] (one reason; one `:dispose ask_client` per subject) and [I have them…] (opens group 4's form).
   - Footer: "Download the request as Excel" (`request-download`).
   - Rows already asked read "Waiting on the client · asked 14 Nov".
8. **Model checks (3)**.
   - Only the open readiness checks, in words, each saying where it is fixed.
   - "PK-Sim test load: runs on the server only."
   - "How values are chosen: when sources disagree, the client's value comes first, then the best-graded paper. Values are never averaged. Source selection rules v0.1 · UNVERIFIED."
   - Testids `readiness` and `check-<raw name>` are kept.
9. **Blocks nothing (n)**, collapsed.
   - Holds Delivery clean-up whose subjects are all confirmed through the sheet form. On clientamide that is the 45 template header cells and the 5 layouts.
   - Line: "45 loose numbers and 5 table layouts in files confirmed with the sheet form. They block nothing; tidy them for the delivery record."
10. **Done (n)**, collapsed. What was settled in this session, and confirmed subjects with an "In the model" link.

Empty state (`inputs-ready`): "Everything the model needs is here." with the button [Go to Review & sign].

## Tab Compound

- **Open here.** The To do rows for this area, at most 5, then "All in To do".
- **Header.** h2 "Compound" · "3 files feed this area →" (opens Client files filtered) · [Search the sources and the literature] (`ask-literature`) · [Take the published OSP model's values] (`published-model-*`) · Add data ▾.
- `LiteratureProgress` while the search runs. Then "What the structured sources gave" (`sources-read`), open while new and folded afterwards.
- The client's compound values to confirm, if any, as a unified card.
- **Parameters by building block**, from the registry, in this order: Identity and physico-chemistry · Binding and partitioning · Permeability and absorption · Elimination, by process (the bare id `elim` is fixed to land here) · Transporters and interactions.
  - Block header: "Identity and physico-chemistry · 4 missing".
  - One-line row: label with a symbol or unit hint (CPF id only in the title tooltip) | value, or an inline [Add value] | source · year · grade · "+1 agree" | one state word | peek | ⋯ (Sources, Exclude a source).
  - A missing row carries a single red accent and nothing else ("—" and "no source yet" are removed).
  - Unsourced optional parameters fold under "+ 7 more you can fill in".
  - Parameters not on this project's data plan are listed read-only.
- `ValueReuse` and `AccessRequests`, folded, at the end.

## Tab Products and dissolution

- Open here, then the header with the files link and Add data ▾.
- **Products named in the proposal.** `BriefList`, editable, as a compact table. Empty state: "Products named in the proposal: none yet. Add the ones the model must simulate."
- **One `ProductCard` per unified product**, folded except the first open one:
  - name · role (RLD / Test, as text) · strength · batches · dosage form;
  - dissolution per medium: observed points in `--obs`, the Weibull fit in `--sim`, the same legend everywhere; t50 and shape; f2 against the reference (`f2-row`);
  - [Use as release] (`Dissolution` propose);
  - "Used by 230-23, 231-24";
  - "Kept, not used by the model: dosage form, particle size d50, polymorph" (the held-back list, moved here);
  - "Fed by Dissolution RLD pH 6.8.xlsx · pH 6.8 →" (the file row);
  - any sheet-form sheet to check (`DraftItem`);
  - the single confirm path.
- "Sheets not linked to a product (3)". On exampleamide these are the pH 6.8 Test, pH 6.8 RLD and client-raw sheets; each can be linked or checked.
- Formulation of each solid study, shown only when a used solid study exists (`formulation-<id>`).
- Formulation values (`InputRows`). Empty state: "No formulation in the model yet. Confirm a product's dissolution above, or choose a release model."

## Tab Clinical studies

- Open here. Header with the files link and Add data ▾: Upload · template (`download-template`) · Digitize (`open-digitizer`) · Type a table (`type-table`) · Find observed data (AI, `find-observed`).
- **Study list** `studies-list`: `DataTable` with `useTableView`; chips All / To confirm / In the model / Left out.
  - One row per unified study: Study (aliases underneath) | Design · route · dose | Data (values, datasets) | one status word | Role | expand.
  - Row testid `study-row-<key>`. A row expands into its `StudyCard`.
- **StudyCard** `study-card-<key>`, from top to bottom:
  1. Header: title (ink, 600, 17 px), aliases, one status, ⋯ (Peek source · Confirm with the sheet form instead… · Show separately).
  2. Facts: a labelled `dl` with mapped field names.
  3. The observed profile: `DatasetView` at full card width, with the NCA caption.
  4. This study's datasets: one row each with state "waiting for confirmation" / "in the model" / "left out", a "not in the data plan" chip, and one Leave out.
  5. What still blocks: the subject's own blockers, plus one line `delivery-gate-<subject>` for the delivery-wide clean-up.
  6. Facts to fill (`FactsForm`), disagreements, and sheets to check.
  7. The confirm path: either the sheet-form footer (`confirm-<group>`) or the spot check and "Confirm and sign…" (`delivery-confirm-<subject>`).
  8. "How the files were read", folded and read-only: value tables, layouts linking to To do, and source peeks.
  9. After confirmation: "In the model: study 230-23 · role S2 · 1 dataset →", linking to `#study-<id>`.
- **In the model.** `StudiesTable`, rows `study-<id>`. Empty state: "No study confirmed yet. 5 studies wait for confirmation above."
- **Other observed data** (literature, digitized, agent). `ObservedDatasets` for datasets on no study card; `observed-datasets` kept.

## Tab Populations and individuals

- Open here (demographics).
- Populations the proposal names (`inputs-populations`).
- **Each study's individual**, one row per unified study:
  - confirmed: today's form (`individual-<id>`);
  - Delivery path, not confirmed: the same fields, saved through `:enter`, "loads when the study is confirmed";
  - sheet-form path, not confirmed: "Enter once the study is confirmed →".
- Values set on the individual. Empty state: "None yet: expression and individual values appear when a source gives them."

## Tab Simulation settings

- One line: "PK-Sim's default calculation methods and solver settings are used. Each study runs over its full sampling time. Dosing for predictions is set on Review & sign."
- [Change…] reveals `InputRows` (settings) and the solver rows per study (only when studies exist).
- No empty card, and no 300 px dead band (inputs.css:61 fixed).

## Tab Client files (`tab-files`)

- **Header.** "Client files (9)" · [Add files] (with an area select; `client-upload-files`) · [Read all again] (`delivery-run`) · Document Library link.
- **AI reading line** (`reading-tray`, with `reading-tray-counts`, `-agent`, `-toggle`, `-backlog`, `read-library`, the figure suggestions and Digitize). Off: "AI reading is off. The files were read without AI."
- **Delivery line.** "Received 14 Nov 2026, 18:15, by dev-user · 9 files read · 72 numbers not read · 5 loose numbers · 366 values not linked to a study". The renamed tiles sit behind Details (`delivery-coverage`, `delivery-total-*`). Chip `delivery-rules`: "Intake rules v0.1 · UNVERIFIED".
- **FilesTable** `files-table`, one row per file (`inputs-file-<name>`):
  - File (name, kind select `file-tag-*`, tag proposal `tag-proposal-*`);
  - Area;
  - Read: one state (`delivery-file-state-<id>`): read / partly read / waiting for AI / failed / not supported;
  - Gave: "Studies 230-23, 231-24 · 79 values";
  - Still needs you: chips that link to To do rows;
  - ⋯ menu: Read again (`delivery-file-run-<id>`) · Read with AI · Open in the library.
- **Row expanded** (`delivery-file-toggle-<id>`):
  - Tables and text (`delivery-regions-<id>`): Where ("Sheet1 · A4:M12" / "page 3") | What | Layout (status and "Check layout") | Numbers (read / not data / not read, right-aligned) | ⋯ Mark as not data.
  - Loose numbers, with a batch action.
  - The sheet form's sheets (`client-file-*`, `sheet-*`). "Check the reading" opens `SheetReader` (`reader-*`). "Read this sheet" is hidden when the delivery already read the sheet. Agent buttons appear only while AI is on.
  - Dissolution profiles fed by the file.
  - "Technical details" (`delivery-stages-<id>`: stage times, run attempt, delivery id).

## Where every old block went

| Old block | New place | How |
|---|---|---|
| ReadingTray (InputsWorkspace.tsx:290) | Client files › AI reading line; status-line note | merged |
| Delivery head, summary and tiles (DeliverySection.tsx:202-213, 152-175) | Client files › Delivery line + Details | collapsed |
| What arrived / FileItem (:228-238, 40-143) | FilesTable rows and FileDetail | merged |
| Still to ask the client (:240-259) + ClientRequest (InputsWorkspace.tsx:323) | To do › Ask the client | merged |
| Mappings list (:261-278), card "Mappings no person approved" (SubjectCard.tsx:448-466), region Mapping chip (:84-89) | To do › Check how tables are read; Layout column as a link | merged |
| Study not stated (Unassigned.tsx) | To do › Link values, one row per file | merged |
| To review and confirm list (:282-306) | Cards in their areas | removed (duplicate) |
| Outside-number forms on cards (SubjectCard.tsx:368-385) and per file (DeliverySection.tsx:109-125) | To do › Numbers not read (+ FileDetail) | moved |
| SILENT / OUTSIDE / UNASSIGNED blockers on every card | One gate line per card | collapsed |
| Still missing to run panel (InputsWorkspace.tsx:309-334) | To do | merged |
| Readiness and sources (:336-357) | To do › Model checks | moved |
| To confirm filter (:295-299) | Status-line To confirm count | merged |
| Files drawer (:111-150, 456-462) | Client files tab | merged |
| FilesBar / FilesHere (TabFiles.tsx:44-88) | Area header link + Client files | removed (duplicate) |
| Group index pills (ClientConfirm.tsx:236-245) | Study list rows | removed (duplicate) |
| StudiesTab TodoCards (:260) | Open here / To do | moved |
| "No studies yet" (:261) | Rewritten empty state of "In the model" | rewritten |
| "Delivered, not in the data checklist" (:272-277) | Chip on dataset rows | merged |
| "Add observed data" paragraph (:278-293) | Add data menu | collapsed |
| Every dataset | Study cards + Other observed data | regrouped |
| "Dissolution (2 profiles)" (InputsWorkspace.tsx:394-397) | Product cards | merged |
| Solver card (:425-445) | Settings › Change… | collapsed |

## Capability map: everything still reachable

- **Delivery:**
  - reading: read again (all files or one), stage times, region "not data";
  - files and values: outside items one by one or in batch, link values with study, arm, product, batch or a new one;
  - layouts: approve, reject and edit;
  - subject decisions: override a check, enter a value, correct a value, keep one of conflicting values, confirm or refuse a link, dispose a required item;
  - confirmation: spot check, confirm and sign.
  These live in the cards, To do and Client files. On a sheet-form card the Delivery forms sit behind "Edit the file reading (does not change what this card confirms)".
- **Sheet form:**
  - review: select and reopen an issue, fill and finish a draft, confirm a group;
  - files: SheetReader, the read and sort agents (AI on only), retag, use or keep a tag proposal;
  - data: propose a release model, f2, log or linear charts;
  - also the typed table, template download, digitize, find observed data, and leaving out a dataset or study.
- **Inputs:**
  - values and sources: add a value, exclude a source, keep one of conflicting values, pKa, check a held value, correct, process choice, formulation choice, regimen;
  - people: individuals, edit populations and products;
  - from elsewhere: literature search, published model, value reuse, access requests, request download.

## One work model

## One work model, one list, the same numbers everywhere

`lib/inputsWork.ts` holds pure functions (no React), unit-tested by `e2e/inputs-work.spec.ts`:

- `unifySubjects(delivery: DeliveryPage, review: ClientReviewPage)` returns `UnifiedSubject[]`;
- `buildWork({inputs, review, delivery, clientData, readingQueue, cards})` returns `WorkItem[]`;
- `countBy(items, 'status' | 'area')`.

`components/inputs/useInputsWork.ts` composes the existing reads: `/inputs`, `/client-review`, `/delivery`, `/client-data` and `/reading-queue`. Subject cards (`/delivery/subjects/{type}/{id}`, 25-120 KB each) are loaded lazily for the unconfirmed subjects on the Delivery path:

- after first paint, through `requestIdleCallback`;
- with `useQueries`, at most 2 at a time;
- cached with a 60 s staleTime.

Until a card arrives, its row shows a skeleton chip ("checking…").

```ts
type Status = "missing" | "to_confirm" | "to_decide" | "done";
type WorkItem = {
  key: string;            // stable: layout:<mapping_id> · link:<file sha> · notread:<file sha> · fact:<subject>:<field> · s0:<cpf id>
                          // issue:<group>|<issue> · conflict:<subject>:<id> · confirm:<subject key> · ask:<req_id> · check:<name>
  status: Status; group: "ready"|"layouts"|"link"|"notread"|"facts"|"disagree"|"confirm"|"ask"|"checks"|"tidy"|"done";
  area: Tab; title: string; detail?: string;
  subjects: string[];     // unified subject keys it concerns
  blocks: string[];       // subject keys whose signed confirmation it holds up (empty means the "Blocks nothing" group)
  files: string[]; source: "delivery"|"sheet-form"|"inputs";
  home: { tab: Tab; anchor: string }; inline?: "layout"|"link"|"notread"|"facts"|"s0"|"issue"|"conflict"|"linkq"|"ask";
  weight: number;         // values held or blocked; orders rows within a group
};
```

All counts come from this one model:

- the status line (Missing / To confirm / To decide / Done);
- the tab badges, counted by `area`; the Client files badge counts file-level items;
- each area's "Open here" strip, filtered by area;
- each card's blocker list, filtered by subject;
- each file row's "Still needs you" chips, filtered by file;
- the step bar's line, mapped from the same readiness checks.

So "To confirm 12" means 12 cards, the Clinical studies badge equals its Open here rows, and so on. The Delivery numbers (10 layouts, 366 values, 72 + 5 numbers), which today count nowhere, are counted.

## How the two pipelines become one list (no study, file or value shown twice)

**Join of subjects.** The precedence is fixed, never crosses types, and never merges two Delivery subjects:

1. a legacy item id appears in `DeliverySubjectRow.loaded_elsewhere`;
2. same type and the same normalised label ("Study 230-23" ↔ "230-23");
3. same type, and a shared source file (`item.source.doc_sha256` ∈ `row.files`) that holds exactly one Delivery subject of that type;
4. legacy `sheet` groups attach to the Delivery subject that holds values from the same file and sheet; otherwise they go to "Sheets not linked to a product/study" in their area;
5. otherwise the subject is legacy-only.

**Results on the seeds** (written into the unit spec):

- exampleamide gives 12 cards.
  - Sheet-form path: CL-01, 230-23-REF, 230-23-TEST, Nichols2012-IV, Test 10 mg, Brand 10 mg.
  - Delivery path: 230-23 (+ the legacy 230-23 Fasting draft), 231-24 (+ its legacy group), 230-25, 230-26, Exampleamide IR tablet (+ the sheet "Dissolution · messy-delivery.xlsx"), Comparamide tablet.
  - Plus 3 unlinked dissolution sheets.
- clientamide gives 5 sheet-form cards.

**Confirm path per card:**

- `delivery.confirm_on==='delivery'` → **Confirm and sign**: Delivery blockers, spot check, `ConfirmDialog` with step-up.
  - The legacy footer is hidden; the legacy reading appears in "How the files were read".
  - "Confirm with the sheet form instead…" stays in the card's ⋯ menu, with the warning "Whichever is confirmed first is what loads; the other loads nothing twice" (client_api.py:546-580).
- Legacy group present (template or legacy-only) → **Confirm**: the legacy `GroupCard` body.
  - The Delivery reading is folded and read-only. Its forms sit behind an explicit "Edit the file reading" toggle, which affects nothing this card confirms.
- `client-review` with no legacy card → read-only, with "Its card is not available yet: read the file again from Client files".

**Aliases instead of second lists.**

- The 230-23 card says "also read as 230-23 Fasting by the sheet form".
- A legacy-only 230-23-REF card says "Its values are not linked to a study in the delivery yet → Link it".
- The file's Link row says "Also read by the sheet form as 230-23-REF → open that card".
- Once the person links that file to 230-23, arm Reference, rule 3 merges the 230-23-REF card into 230-23 automatically.

**Other duplicates resolved:**

- *Facts.* Delivery gaps and LANDING_FIELD_MISSING are merged by field, and the legacy draft "needs" are shown only on sheet-form cards. One form asks once: route, n and purpose are no longer asked twice.
- *Disagreements.* Only the confirm-path pipeline's conflicts are shown, so the EX-101 dose is asked once.
- *File status.* One status merges `DeliveryFile.state` (shown as "partly read" when `regions_unread > 0`), the reading-queue state (shown only while AI is on) and the legacy reading. "0 of 9 read · 9 waiting" can no longer sit beside "9 read".
- *Loaded chips.* "Loaded" is shown only for ACCEPTED datasets. A PROPOSED dataset shows "waiting for confirmation" (`ObservedDatasets.standing`).

**The delivery-wide gate is made visible, not hidden.**

- SILENT_LOSS, OUTSIDE_NUMBERS and UNASSIGNED_VALUES are filtered out of each card's blocker list. In their place comes one line, `delivery-gate-<subject>`: "Waits for the delivery clean-up (9 files received 14 Nov): 10 layouts · 6 files to link · 77 numbers not read → To do". It is computed from the coverage of the files in `row.deliveries`.
- The To do items for that delivery carry `blocks` = its subjects on the Delivery path. Where all of a delivery's subjects confirm through the sheet form (clientamide), the items fall to "Blocks nothing".

## How the person works through it

- **Priority** is dependency order: Ready now → layouts → link → numbers not read → missing → disagreements → confirm → ask the client → model checks. Within a group, rows are ordered by `weight`.
- **"Next"** in the status line focuses the first row of the first non-empty group.
- **Inline or at home.**
  - Batch and file-level decisions are made inline in To do: layouts (dialog), link, not read, missing facts, compound values, disagreements, ask the client.
  - A subject's confirmation is made on its card. "Open" moves to the card's area and shows the review bar (‹ Previous · 4 of 12 · Next ›), so the person walks the confirmations without coming back each time.
- **Batches.**
  - Each batch has checkboxes, a sticky `BulkBar` and **one** reason, offered as suggestion chips (file name or title says 230-23; "a column header, not a value"; "a note, not data"; "asked in the data request of 14 Nov").
  - The person must still press the button. The reason stays required and editable.
  - The request is sent once per file or per destination; the API already takes arrays (`DeliveryAssignment.targets`, `DeliveryExclusion.regions`).
  - Partial failures are listed per row.
- **After each decision:**
  - focus moves to the next row's first control, or to the group heading (tabIndex -1) when the group is done;
  - a polite live region announces it ("vessel_1…vessel_12 marked as not data. 33 loose numbers left.");
  - Dialog falls back to the list heading when its opener is gone.
- **Buttons** stay enabled. On submit, an inline message names what is missing ("Pick a study or a product"), linked with aria-describedby.

## How the person fills what is missing (the owner's "make all data available downstream")

- **Compound.**
  - The rows of every model-placed registry parameter are rendered, not only the 6 S0 to-dos (API 1).
  - Missing S0 values can be entered as a batch with one shared citation (`POST /evidence`, unchanged).
  - `AddValue` gets visible labels.
- **Study facts.** A typed `FactsForm`:
  - Route and Purpose: selects from `study_options`;
  - n: a number;
  - Dose: a value with a unit;
  - Matrix: a select, posted through `:enter` with field `matrix` (a path that exists today);
  - Analyte: a select of the brief's parent drug and its metabolites, plus "a new analyte…" (API 2).
- **Arms and batches.** "a new arm…" and "a new batch…" in the Link table, pre-filled from the caption ("Reference", "Test"), so the 230-23 Test and Reference files no longer collide (API 2).
- **Numbers not read.** They are listed cell by cell and can be marked as not data per cell (API 3). An unread or rejected table gets "Read this table…" with a structured layout editor (API 4).
- **Demographics.**
  - "Enter them…" on the requirement: population, sex, age mean or range, weight, through `:enter` with the field names from `modeler_intake.fields`.
  - On a confirmed study, through `datasets:study` (today's path).
  - Otherwise "Ask the client".
- **Downstream visibility.** The status line shows "In the model: …", built from /inputs (studies by role, formulations with a release model, compound values kept) and linked to Review & sign. Each confirmed card links to its row in "In the model".

## Components

## New (apps/web)

**Logic and words**
- `lib/inputsWork.ts`: pure. `unifySubjects`, `buildWork`, `countBy`, `suggestTargets` (from caption, file name and legacy title; never from a blinded caption), `gateFor(subject, page)`.
- `lib/words.ts`: the fixed vocabulary and the label maps.
  - `STATUS_WORD`;
  - `FIELD_LABEL` (n → "Subjects (n)", lloq → "LLOQ", food_state, intended_use → "Purpose", strength_mg …);
  - `VALUE_LABEL` (SD → "single dose", ir_tablet → "IR tablet", arithmetic_mean …);
  - `BLOCKER_TEXT` and `CHECK_CODE_TEXT` (ANALYTE_MISSING → "analyte not stated" …);
  - `READINESS_LABEL`, keyed by the raw check name;
  - `anchorText(where)`: `s:'Sheet1'!A4:M12` → "Sheet1 · A4:M12"; `p:3/w:…@…` → "page 3";
  - `coverageText`, which lists only the non-zero problems.
  `lib/plain.ts` stays for the references.
- `components/inputs/useInputsWork.ts`: the composed hook, with lazy subject cards.

**Page frame**
- `components/inputs/InputsStatus.tsx`: the status line and the Next button.
- `components/inputs/AddDataMenu.tsx`: the head menu, and its per-area subset.

**To do tab** (`components/inputs/todo/`)
- `TodoQueue.tsx`, `TodoGroup.tsx`, `TodoRow.tsx`.
- `LayoutQueue.tsx`: rows plus `MappingReview` in queue mode.
- `LinkTable.tsx`: replaces `delivery/Unassigned.tsx`.
- `NotReadTable.tsx`: silent cells, loose numbers and unread regions, with batch actions.
- `FactsForm.tsx`: typed study facts. Shared by Delivery gaps and LANDING_FIELD_MISSING (`:enter`) and the legacy `DraftItem` needs (keeps the `need-*` / `prefilled-*` testids).
- `StateIt.tsx`: analyte and matrix.
- `MissingValues.tsx`: batch S0 entry, reusing the `AddValue` fields.
- `AskClient.tsx`: merges `ClientRequest.tsx` and the request block of DeliverySection.tsx:240-259.

**Cards** (`components/inputs/cards/`)
- `StudyCard.tsx`, `ProductCard.tsx`.
- `ConfirmPath.tsx`: chooses the legacy `GroupCard` or `DeliveryReview`.
- `HowRead.tsx`: the folded, read-only other reading.

**Client files tab** (`components/inputs/files/`)
- `FilesReceived.tsx`, `FileRow.tsx`.
- `FileDetail.tsx`: the regions table on `DataTable` + `useTableView`; the ClientFiles sheets inside.
- `AiReading.tsx`: the tray content. `ReadingStatus` stays exported for `library/AddData.tsx`.

**Kit** (`components/kit/`)
- `BulkBar.tsx`: a sticky selection bar with count, Reason and action.
- `Reason.tsx`: replaces `delivery/shared.tsx` `Why`. Adds `suggestions`, a "use last" chip (sessionStorage per project and decision kind; never auto-filled), a required check on submit and aria-describedby. Keeps the `${testId}-why` / `-submit` scheme.
- `Menu.tsx`: an accessible ⋯ overflow menu.
- `ReviewBar.tsx`: the Previous / Next bar under the area bar.
- `LiveRegion.tsx`.

## Rewritten

- `components/inputs/InputsWorkspace.tsx`: the frame (head, status, area bar, panels).
  - Deleted from it: ReadingTray / DeliverySection (:290-291), `FilesDrawer` (:111-150), `.rail-side` / SidePanel / details (:309-357), the hero lede and actions (:271-285), the empty Solver card, and the `initialTab = "compound"` default (now To do while anything is open).
  - Loading uses `PageSkeleton`. The root carries `data-no-reveal`.
- `components/delivery/SubjectCard.tsx` becomes `DeliveryReview.tsx`.
  - Props: `mode: 'confirm'|'read'` and `gate`.
  - The delivery-wide blocker codes become the gate line.
  - The outside list (:368-385) moves to `NotReadTable`.
  - Gaps and LANDING_FIELD_MISSING merge into `FactsForm`.
  - ANALYTE_MISSING and MATRIX_MISSING get "State it…"; DISSOLUTION_METHOD_INCOMPLETE gets "Fill in…", with Override kept as "Accept as is…".
  - `RequirementRow` gains "Enter them…".
  - The "Mappings no person approved" list (:448-466) becomes a link to the layout rows.
  - MAPPING_NOT_APPROVED is excluded from `flagged` (:325-330) and stays on the table header.
  - Check messages are mapped to words and mp- ids to table titles.
  - The values tables use one shared `<colgroup>`, `table-layout: fixed`, and below 600 px rows render as stacked items; censored values show a `<LLOQ` chip with a tooltip.
  - The `delivery-card-*`, `delivery-blocker-*`, `delivery-enter-gap-*`, `delivery-dispose-*`, `delivery-confirm-*`, `delivery-source-*`, `delivery-manifestation-*` and `delivery-ready-*` testids are kept.
- `components/delivery/MappingReview.tsx`.
  - Queue mode: Previous / Next / "Approve and next" / "3 of 10" in a sticky action bar at the bottom of the dialog; the columns table first.
  - Opens at the row's version; the GET already supports `?version`.
  - Header names instead of column numbers.
  - A structured editor: per-column selects for role, field, unit and statistic, plus a "Read once for the whole table" row. It builds the spec in the browser and posts to the existing `:edit`. JSON stays as "Edit as JSON (advanced)".
  - Copy per the glossary.
- `components/delivery/DeliverySection.tsx`: **deleted**. Coverage goes to FilesReceived Details, FileItem to FileDetail, mappings to LayoutQueue, request to AskClient, subjects to the cards, Unassigned to LinkTable.
- `components/delivery/shared.tsx`: the maps move to `lib/words.ts`. `Why` is re-exported as kit `Reason` so the stepwise migration compiles. FILE_STATE shows "partly read".
- `components/delivery/ConfirmDialog.tsx`, `SpotCheck.tsx`: copy only.
  - "Start the spot check", "in progress", "values changed: start again".
  - "From the files: 72 numbers not read …"; "Intake rules v0.1 · UNVERIFIED (SME sign-off pending)".
  - The step-up flow is untouched. The spot-check legend reads the field and time, not `v.id`.
- `components/inputs/ClientConfirm.tsx`.
  - `GroupCard` is exported.
  - `ConfirmGroups` and its index (:217-252) are deleted.
  - Copy per the glossary: one chip "2 facts to fill in"; footer "Fill in the missing facts above, then confirm." / "Ready. Confirming adds this study to the model under your name."; button "Confirm study 230-23". The `confirm-*` / `group-*` / `issue-*` / `toggle-*` testids are kept.
  - `PeekButton` reserves its 32 px slot.
- `components/inputs/StudiesTab.tsx`.
  - Keeps `StudiesTable` (the "In the model" section) and `TypedTable`.
  - Removes the TodoCard loop, the EmptyState, FilesHere, the unpromised list and the add-data list (:260-293).
- `components/inputs/InputRows.tsx`.
  - Regex `/^(elim|metab|clear)(\.|$)/`.
  - A missing row shows a single accent and an inline Add value.
  - Optional empty rows are folded.
  - `AddValue` gets labelled `.field` controls, and Cancel sits next to Add.
  - "· n missing" in the block heading.
  - The CPF id moves to a tooltip.
- `components/inputs/IndividualsTab.tsx`: rows for every unified study; `:enter` for the Delivery path; empty-state copy.
- `components/inputs/ObservedDatasets.tsx`.
  - `standing()`: PROPOSED → "waiting for confirmation".
  - A filter for datasets on no card.
  - A single Leave out.
  - Agent buttons hidden when AI is off.
- `components/client/ClientFiles.tsx`.
  - Used only inside FileDetail; its table is wrapped in `.table-scroll`.
  - "Check the reading" on sheets already read.
  - Agent buttons only while AI is on.
  - The `.chip.brand` uses are fixed by the CSS scope below.
  - `Dissolution` is used per product.
- `components/inputs/DatasetView.tsx` and `ClientFiles` charts.
  - SVG width from a ResizeObserver, viewBox = box width, so ticks stay 11-12 px.
  - Observed points in `--obs`, fit in `--sim`, one legend.
  - `.seg { flex-wrap: nowrap }`.
- `components/inputs/TabFiles.tsx`: `FilesBar` and `FilesHere` are deleted; `fileArea`, `whereShown` and `AREA_LABEL` are kept for FilesReceived.
- `components/inputs/ReadingTray.tsx`: the tray body moves to `files/AiReading.tsx`; `ReadingStatus`, `foundText` and `trayLine` are kept.

**Kit changes**
- `kit/Tabs.tsx`: `countLabel` (sr text "to do") and a `sticky` class hook.
- `kit/Stepper.tsx`: maps reasons through `READINESS_LABEL`; a `static` variant.
- `kit/Dialog.tsx`: a `returnFocus` fallback.
- `kit/SourcePeek.tsx`: `PeekButton` with a visible "Source" label variant and a reserved slot.

**Hooks**
- `lib/hooks.ts`: `useMutation({ invalidate?: QueryKey[]; routerRefresh?: boolean })`. The default stays as it is for other pages.
- `useDecide` invalidates only `/delivery` and `/delivery/subjects/*`. A confirmation still refreshes everything.
- The end-of-reading refresh (DeliverySection.tsx:189-193) moves to `useInputsWork`, scoped to delivery, client-review, client-data and inputs.

## CSS approach

Existing files are edited; no new framework; tokens are in `app/globals.css`.

- **globals.css**
  - Type tokens `--fs-meta:12px; --fs-body:14px; --fs-row:15px; --fs-card:17px; --fs-section:20px`, replacing the 11.5, 12.5 and 13.5 px sizes on Inputs.
  - `--control-border: #8a8a8e` (3:1).
  - `--warn-ink: #9a4500` and `--pass-ink: #17663a`, for AA on tints. This also separates the "needs you" text from `--obs`, which stays the chart colour across the app.
  - One base control rule: `:where(input:not([type=checkbox],[type=radio],[type=file],[type=range]),select,textarea){font:inherit;font-size:var(--fs-body);min-height:36px;padding:0 12px;border:1px solid var(--control-border);border-radius:var(--radius-sm);background:var(--surface);color:var(--ink)}`, with `select{appearance:none; padding-right:32px}` and an SVG chevron.
- **design.css**
  - `.brand` is scoped to `.sidebar .brand` (fixes the 350×40 `.chip.brand`).
  - `.stepper-wrap.static{position:static}` on Inputs.
  - `.stepper-wrap.compact .step-waiting{display:none}` (removes the dead click strip).
  - The `.rail-*` overrides (:198-209, :406-407) and `.missing-list` max-height are deleted.
  - `scroll-padding-top` is set from the area bar's height.
- **inputs.css**: rewritten for `.inputs-status`, `.area-bar` (sticky, opaque, hairline), `.todo-group` (one amber left accent per open group), `.todo-row`, `.work-table` and `.review-bar`. `.inputs-area{flex:1 1 auto}`. The old `.rail-*` and `.confirm-group.to-confirm` amber borders go.
- **delivery.css**: trimmed to the card internals; `.delivery-values` gets fixed layout and stacked rows below 600 px.
- **kit.css**: `.btn.small` moves here from start.css:136; `.btn.tiny` is retired; `.inline-issue` gets square corners on its bar side; `.bulk-bar` and `.menu` are added.
- **client-data.css**: `.linkish` and `.file-tag select` are dropped (the base rule covers them); `.profile-chart svg` loses its max-width.
- **Button roles.** Primary: one per region (the page's Next; an open card's Confirm). Secondary: a neutral pill, 36 px (30 px small). Tertiary: one text-link style, `.link-btn`.
- **Chips.** A status chip is neutral fill plus a word. Tab counts are neutral.
- **Motion.** `lib/motion.ts` `prepare()` skips `[data-no-reveal]`.
- **Phone.** Below 900 px: one-row scrolling area bar; a single-line static stepper; stacked LinkTable and value rows; BulkBar fixed at the bottom; no horizontal page scroll.

## API changes

Each change is additive to an unlocked file and comes with `docs/api/openapi.json`, `npm run api-types` and a CHANGELOG entry. Python tests carry the delivery and inputs `req` tags already used in `services/api/tests/test_delivery_api.py` and `packages/project-model/tests`. No SME-governed ruleset, requirement template, acceptance criterion, `intake_rules.yaml`, registry or other locked file changes; the registry is only read.

**1. GET /inputs: a row for every fillable registry parameter.**
- **Why:** today only the 6 S0 to-do rows exist, so a person cannot enter permeability, the blood-to-plasma ratio, fe, fm or clearances.
- **Change:** `packages/project-model/src/modeler_project/inputs_view.py` `compound_rows` (:48) adds, for each exact registry key with `placement: model` and an owning requirement (`_requirement_of` gives a `req_id`), a row with the new state `"empty"`. Families and keys the data plan does not cover are omitted.
- **Schema:** `services/api/src/modeler_api/views/inputs.py:47` `CompoundRow.state` gains `"empty"`. "Empty" is not "missing", so S0, readiness and the to-do list are unchanged.
- **Writes:** values go through the existing `POST /evidence`, whose `target_problem` already accepts model-placed ids.

**2. POST /delivery/values:assign: create arms, batches and analytes, and state the matrix.**
- **Why:** the 230-23 Test and Reference files collide on subject 001 · period I; CL-01's profile cannot land because analyte and matrix cannot be stated.
- **Request:** `DeliveryAssignment` (delivery_routes.py:930-942) gains `new_arm`, `new_batch` and `new_analyte` (labels, max 80 characters), plus `analyte` (an entity id).
- **Backend:** `intake_review.assign` (:583) gains the same arguments. `Ledger.name_entity` (ledger.py:815) creates `arm` under the study, `batch` under the product and `analyte`, with the same duplicate check (409 naming the existing one).
- **Options:** `InputsPage.study_options` gains `analyte` (the brief's parent drug and its named metabolites) and `matrix` (the intake vocabulary's matrix words, read, never typed in the web). Matrix itself goes through the existing `:enter` with field `matrix` (study_routing.py:92-99), so no new route is needed.
- **Optional, needs the owner's agreement:** a `conditions` merge (keys validated against `routing.item_fields`), so "no apparatus stated" can be supplied instead of only overridden.
- **Note:** science-adjacent.

**3. Silent cells: list them and set them aside one by one.**
- **Why:** 72 "silent" cells block every signed confirmation. Nothing lists them, and the only remedy is discarding a whole table.
- **Read:** `DeliveryRegion` (views/delivery.py:113) gains `silent_cells: [{where, text|null}]` (capped at 50; `text` null for a blinded file) and `silent_more: int`, from `RegionCoverage` (coverage.py:198-215) via `_regions` (delivery_routes.py:403-418).
- **Write:** `DeliveryExclusion.scope` (:945-949) gains `"cells"`, handled in `intake_review.exclude_regions` (:745) and counted as excluded in coverage.
- **Note:** this changes what counts as excluded, an intake-contract change. It needs a CHANGELOG entry and the owner's review.

**4. POST /delivery/mappings:propose, and the layout vocabulary.**
- **Why:** an unread or rejected table can never get a first layout, because `:edit` returns 404 (`_versions` :1172-1176). Corrections today are raw JSON.
- **Route:** `POST /delivery/mappings:propose {file_sha256, region_id, spec, why}` computes `layout_fingerprint(region_grid(doc, region_id))`, calls `MappingCache.propose(origin='person', first_seen=(sha, region))`, then `_read_again`.
- **Vocabulary:** `GET /delivery/mappings/{id}` gains `vocabulary: {roles, fields, statistics}`, read from `modeler_intake.mapping_spec` and `fields`, so the structured editor's selects are never invented in the web.

**5. Demographics entered through :enter must count as found (no contract change).**
- **Why:** a person who has the demographics must be able to enter them, not only "ask the client".
- **Check:** confirm that `study_requirements.requirement_status` counts person-entered study facts (`:enter` with `modeler_intake.fields` names) as found for REQ-sys.demographics. If not, fix it there (unlocked).
- **Not touched:** `core_small_molecule.yaml` (locked, SME).

**Deliberately not changed (owner or SME decisions, raised in risks):**
- the per-delivery gate (contracts §11.10);
- the template header cells counted as "outside numbers" (an intake rule);
- excretion, product attributes and occasions mappings blocking although they never land;
- retiring a pipeline (`intake_pipeline`).

**Deferred, not needed to fill anything:**
- a slim `/delivery/status` for polling;
- per-file paging of `unassigned` (the 692 KB payload);
- per-subject open counts on `DeliverySubjectRow`;
- `subjects/{type}/{id}:merge` for a later file that names a study a person created (ledger_entities.py:246-251).

## Words

## Status words: only these four on chips, counts and filters

| Word | Meaning | Replaces |
|---|---|---|
| **Missing** | No file or source gives it; you fill it in. | missing, no source yet, —, Missing for S0, Not stated in any file, need, "4 open" on missing rows |
| **To confirm** | The client's data waits for your sign-off. | to review, To confirm · 1 item, The client's data to confirm, Showing what to confirm, waits |
| **To decide** | A choice only you can make: a layout, values to link, numbers to set aside, a disagreement, a check to accept. | waits for approval, to assign, keep one, check it, Settle, open item, need attention, Held until you check it, differs, which study? |
| **Done** | Confirmed, entered or settled. | confirmed and loaded, in the model, Resolved, settled |

Neutral states are allowed only as these exact phrases: "Waiting on the client", "Reading…", "Kept, not used by the model", "waiting for confirmation" (a PROPOSED dataset), "In the model".

## One name per concept

| Concept | Name used |
|---|---|
| Uploads | **Client files** (tab, counts, area link "3 files feed this area") |
| Values to confirm | **Client data** |
| A batch of uploads | **Delivery**: "Received 14 Nov 2026, 18:15, by dev-user" (the "dl-1" id only in Technical details) |
| Region | **table**, **text** or **figure**; never "region" |
| Mapping | **Table layout**: Check layout · Layout approved · Layout to approve · suggested automatically / by the template rules / entered by you · Edit as JSON (advanced) |
| Assign | **Link** values to a study or product: "Values not linked to a study" |
| Silent loss | **Numbers not read**: "in tables, but no column picked them up" |
| Outside numbers | **Loose numbers**: "in notes or text, outside any table" |
| Exclude / set aside | **Mark as not data** (result: "not data") |
| Legacy reader | **the sheet form** ("also read as 230-23-REF by the sheet form") |
| Delivery confirm | **Confirm and sign** |
| Legacy confirm | **Confirm** |
| Agent | **AI**: "AI reading is off · read without AI", "Find observed data (AI)" |
| Request | **Ask the client**: Mark as asked · I have them… · Download the request as Excel |
| Readiness | **Model checks** |
| Downstream | **In the model**: "In the model: study 230-23 · role S2 · 1 dataset" |
| Rules chips (UNVERIFIED stays uppercase, CLAUDE.md) | "Intake rules v0.1 · UNVERIFIED" · "Source selection rules v0.1 · UNVERIFIED" |

## Head and sections

**Head and status**
- Head: eyebrow "Step 2 of 4"; title "Inputs"; lede "Fill in what the model needs and confirm the client's data."
- Status: "9 client files · 6 Missing · 12 To confirm · 19 To decide · 3 done · In the model: …"
- Next button: "Next: Check 10 table layouts →"
- Step bar: "Waiting on you: 6 compound values missing · no observed data confirmed yet · the model can't be built yet"

**To do** ("What needs you" · "Start at the top: each group unblocks the ones below.")
- "Ready to confirm now (3)"
- "Check how tables are read (10)": "A table's layout decides which of its numbers become values."
- "Link values to a study or product (6 files · 366 values)": "These files don't say which study or product their values belong to."
- "Numbers not read (77)": "Numbers no table layout picked up. Mark them as not data, or read the table."
- "Fill in what's missing (n)": "No file or source gives these."
- "Settle disagreements (n)"
- "Confirm the client's data (12)": "Confirming adds a study or product to the model under your name."
- "Ask the client (9)"
- "Model checks (3)"
- "Blocks nothing (n)"
- "Done (n)"

**Gate line**
- "Waits for the delivery clean-up (9 files received 14 Nov): 10 layouts · 6 files to link · 77 numbers not read → To do"

**Card copy**
- Read-only card: "CL-01 comes from the filled client-data template and is confirmed here with Confirm. The file reading below is for reference."
- Footer, items open: "Fill in the missing facts above, then confirm."
- Footer, ready: "Ready. Confirming adds this study to the model under your name."
- Button: "Confirm study 230-23"
- Card chip: "2 facts to fill in"
- Sheet line: "6 subjects × 6 time points · read without AI"
- Legend: "Missing from the sheet: fill in"
- Labels: "Number of subjects", "Dosage form", "Purpose of the study"
- Pre-filled hint: "from the sheet: 6 subject columns (001–006)"
- Save button: "Save these facts"

**Link table**
- Selects: "Choose a study…", "Choose a product…", "a new study…", "a new arm…", "a new batch…"
- Reason placeholder: "Reason, e.g. file name says 230-23"
- Button: "Link"
- Conditions: "USP II paddle · phosphate pH 6.8 · 50 rpm · 900 mL"
- Labels show "Vessel 1", not "vessel Vessel 1"

**Checks**
- "Concentrations don't name the analyte" [State it…]
- "Purpose of the study is missing" [Fill in…]
- "Demographics missing" [Enter them… / Ask the client]
- Override becomes "Accept as is…"
- "Show 2 more checks"

**Spot check**
- "Spot check · not started. Compare a few values with the file: the key study facts plus a random sample. Tick each one that matches."
- Button: "Start the spot check"

**Confirm dialog**
- "From the files: 72 numbers not read, 5 loose numbers, 366 values not linked to a study"
- "Intake rules: v0.1, UNVERIFIED (SME sign-off pending)"

**Held back**
- "Not loaded with this study: CL-01 concentrations, analyte not stated."

**Layout dialog**
- Subtitle: "PK summary table, one row per time point · suggested by the template rules · v1, 14 Nov 18:15 · to approve"
- Read-as: "SD/CV of 'value'"
- Section: "The table (numbers hidden)"
- "Treated as missing: none"

**Dissolution**
- "Pick the profile that best represents release in the body. Its Weibull fit (t50, shape) becomes the formulation's release." [Use as release]

**Products**
- "Each product becomes its own formulation. Add its dissolution data; for a test against a reference, add the study that compares them."

**NCA**
- "NCA from these points (linear-up/log-down, BLQ points excluded)."
- "7 points below the LLOQ are left out (rule: omit)."

**Empty states**
- Studies: "No study confirmed yet. 5 studies wait for confirmation above."
- Individuals: "No study confirmed yet. Each confirmed study gets its individual here."
- Products: "No formulation in the model yet. Confirm a product's dissolution above, or choose a release model."
- Settings: "PK-Sim's default calculation methods and solver settings are used. Nothing to set."
- "Nothing on this tab yet" is never used.

## Model checks labels (keyed by raw name)

| Raw name | Shown as |
|---|---|
| assembly | "Inputs put together" |
| S0 completeness | "Minimum compound data (6 missing)" |
| every pathway placeable | "Each elimination pathway maps to a PK-Sim process" |
| expression profiles | "Enzyme and transporter expression" |
| formulations of solid studies | "A formulation for each tablet study" |
| multiple-dose regimens | "Dosing of multiple-dose studies" |
| demographics stated | "Demographics of confirmed studies" |
| observed data to judge on | "Observed data to compare the model with" |
| observed data are real | "Observed data are real, not test data" |
| every planned simulation builds | "All planned simulations build" |
| Dry run | "PK-Sim test load: runs on the server only." |

## Tab labels

To do · Compound · Products and dissolution · Clinical studies · Populations and individuals · Simulation settings · Client files

## Tests

Two rules hold throughout:
- a testid is kept wherever its element survives;
- each spec is updated in the slice that moves its element, so `npm --prefix apps/web run typecheck`, `build`, `make test` and the e2e suite stay green per slice.

## Specs that change

**delivery.spec.ts**
- Coverage: `tab-files`, then `files-table`. Kept: `delivery-total-*` inside the `delivery-coverage` Details (in the DOM, so `toHaveText` still works), `delivery-file-state-*`, `delivery-file-toggle-*`, `delivery-regions-*` (still "no model is configured"), `delivery-stages-*` (under Technical details, opened first).
- Layouts: `tab-todo` then `todo-layout-<id>`; `delivery-mapping-<id>` stays on the row and the text "waits for approval" becomes "to approve". `mapping-*` is unchanged; `mapping-status` reads "to approve" / "approved".
- Subject: `tab-studies` then `study-row-…`; `delivery-subject-open-*` stays as the card's expand control; `delivery-card-*` is unchanged.
- Blocker loop: OUTSIDE_NUMBERS is removed from the per-card loop and asserted on `delivery-gate-<subject>`.
- The loose-number step uses `notread-<file_id>` with `-why` / `-submit` (it was `delivery-outside-accept-0-*`).
- `delivery-rules` and `delivery-confirm-rules` read "Intake rules v0.1 · UNVERIFIED".
- `delivery-confirm-coverage` reads "72 numbers not read …" (here "0 numbers not read").
- Spot check, step-up, `delivery-signed`, `delivery-landed`, `study-230-23` and `group-study:230-23` are unchanged; the last is read inside the folded "How the files were read".

**client-confirm.spec.ts**
- `to-confirm` becomes the status-line count: it opens To do with aria-pressed. The spec then asserts `todo-confirm-study:EX-101` and opens it.
- `group-*`, `issue-*` and `confirm-*` are unchanged inside the card.

**inputs-data-cards.spec.ts**
- `group-index` and `index-study:*` become `studies-list` and `study-row-study:CL-*`.
- `toggle-study:CL-3` and `files-unplaced` are kept: the second becomes the "Client files" badge chip.

**inputs-workspace.spec.ts**
- Opens `?tab=compound`, or clicks `tab-compound` after asserting `still-missing` on To do.
- `inputs-files` becomes `tab-files`; `inputs-files-drawer` assertions become `files-table`.
- `missing-<kind>-<target>` rows and `missing-demographics-po-md` / `missing-regimen-po-md` are kept and navigate the same way.
- `individual-*`, `study-*` and `inputs-populations*` are unchanged.

**inputs-todo.spec.ts**
- `still-missing` and `missing-*` stay on To do; `todo-<kind>-<target>` stays on the compound rows.
- One added click on `tab-compound` before the `record-*` checks.

**compound-sources.spec.ts**
- `sources-read` and `source-*` are on Compound, open while new.
- `missing-missing-phys.mw` and `still-missing` are kept.

**model-inputs.spec.ts**
- `inputs-ready` becomes the To do empty state.
- `check-every planned simulation builds (software)` is kept (keyed by the raw name), with the label shown in words.

**value-reuse.spec.ts**
- `request-download` stays inside `still-missing`, in the Ask the client group.

**inputs-files-by-area.spec.ts**: rewritten.
- `files-bar-*` and `*-client-files` are replaced by `area-files-<area>` (opens Client files filtered) and `files-table` rows (`inputs-file-<name>`) with an Area column.
- `client-upload-<area>` is kept as the hidden input of each area's Add data menu; `client-upload-files` is new.
- `open-file-*` becomes "Open on <area>" in the row ⋯ menu.
- `file-tag-*`, `tag-proposal-*` and `client-file-*` are kept in FileDetail.
- `inputs-notice` is unchanged.

**Sheet-form specs** (studies-client-sheets, client-data, client-data-guided, inputs-sheets-on-arrival)
- `client-file-*`, `sheet-*`, `reader-*`, `read-result`, `draft-*`, `need-*`, `prefilled-*`, `finish-*`, `cleaning-*`, `f2-row`, `release-*` and `dataset-view` are kept. They now sit in FileDetail (Client files) or the study and product cards. Specs add one `tab-files` click or a row expand.
- `unpromised` becomes `dataset-unpromised-<id>` (client-data.spec).
- `download-template` is in the Add data menu, so the spec opens the menu first.
- `read-agent-*` is hidden while AI is off: studies-client-sheets runs with agents on (check its fixture); otherwise it asserts the "AI reading is off" note.

**library.spec.ts**
- The `reading-tray*` testids stay in `files/AiReading`; the spec opens `?tab=files`.
- `add-data-reading`'s "See each file on Inputs" link goes to `?tab=files`.
- Counts copy: when the delivery read the files, "2 read without AI · AI reading off"; otherwise "0 of 2 read · 2 waiting".

**Unchanged specs:** blinding, table-sort, review-sign, digitize*, source-peek, published-model (`published-model-*` moves to the Compound header; the spec gains a `tab-compound` click), start-*.

**Other**
- zz-ux-shots / zz-ux-seed: the TABS list gains `todo` and `files`; the shots capture the Next flow and the layout queue.
- target-size.spec: new controls are at least 36 px (30 px for small); verify BulkBar and the Menu.

## New tests

- **e2e/inputs-work.spec.ts** (pure, no browser).
  - Imports `../lib/inputsWork` on captured `/delivery`, `/client-review` and `/inputs` fixtures of both seeds (`e2e/fixtures/inputs-work/*.json`, blinded values absent).
  - exampleamide: 12 cards with the expected paths and aliases; 3 unlinked sheets.
  - clientamide: 5 sheet-form cards, with the 45 loose numbers and 5 layouts in "Blocks nothing".
  - Counts equal across the status line, badges and cards.
  - Join precedence; no merge across types; no merge of two Delivery subjects.
- **e2e/inputs-task-first.spec.ts**, at 1440×900 and 390×844:
  - the area bar sits at most 480 px from the top on every tab, and stays sticky;
  - no `[data-testid=delivery-section]`;
  - no horizontal page scroll at 390;
  - one card per study;
  - focus moves to the next row after a decision, run against a route-mocked `regions:exclude` so the shared seeds are not touched;
  - the live region announces;
  - the tab badges equal the Open here counts;
  - the readiness labels are in words.
- **Python**
  - `services/api/tests/test_delivery_api.py`: `new_arm` / `new_batch` / `new_analyte` with the 409 on duplicates; `silent_cells` capped and masked when blinded; scope `cells` counted as excluded; `mappings:propose` re-reads; the mapping `vocabulary`.
  - `packages/project-model/tests/test_inputs_view.py`: "empty" registry rows only with a `req_id`, and S0 and the to-do list unchanged.
  - `test_intake_review.py`: person-entered demographics count as found.
  - OpenAPI snapshot updated.
  - `tests/architecture` untouched; no new boundary exception.

## Slices

Slice 1 reshapes the page (frontend and CSS, no API). Its job is to get the areas out from under the review and fix the visual bugs. Deliverables:
- **Frame.** `InputsWorkspace` is reduced to the frame: compact head with the one-line lede and the Add data menu, a static stepper, the status line and the sticky area bar (all tabs plus **Client files**).
- **Delivery and files.** `DeliverySection` moves, unchanged inside, into the Client files tab, together with the AI-reading line (the old tray). FilesDrawer and FilesBar/FilesHere go; `files-table` arrives.
- **CSS fixes:**
  - the `.brand` scope;
  - the `.inputs-area` dead band;
  - the stepper made static, plus the compact dead-strip fix;
  - the base control style and the `--control-border` / ink contrast;
  - the motion opt-out;
  - the `.missing-list` cap removed;
  - the `elim` regex.
- **Spec updates:** delivery (navigate to Client files), library, inputs-files-by-area, inputs-workspace, the sheet-form specs (Client files).
- **Test:** the area bar sits at most 480 px from the top on every tab, with no horizontal scroll at 390.
- **Records:** CHANGELOG; a new plan `docs/plans/2026-11-14-inputs-task-first.md` recording the deviation from intake-contracts §8.10 ("one slot beside ReadingTray") and from 2026-11-03 §3.2 (left rail → sticky horizontal area bar).

Slice 2 brings one list and one vocabulary (frontend only). Deliverables:
- **Work model.** `lib/inputsWork.ts` (unify and buildWork), `lib/words.ts`, the `useInputsWork` hook.
- **To do tab** as the landing tab, with every group as navigation rows plus the inline groups that already have components: the sheet-form issues, the compound TodoActions, Ask the client (merged, with the download), Model checks (labelled), Ready now and Blocks nothing.
- **Counts.** Status counts, badges, "Open here" strips and the step-bar labels all come from the model.
- **Pipeline copy.** One file status, the false "loaded" chips fixed, `standing()` for PROPOSED datasets.
- **Specs:** inputs-work.spec (pure); client-confirm, inputs-todo, model-inputs, value-reuse and compound-sources updated.

Slice 3 gives one card per study and product (frontend only). Deliverables:
- **Cards.** StudyCard, ProductCard and ConfirmPath.
- **Delivery review.** `SubjectCard` becomes `DeliveryReview` with read and confirm modes, the gate line, MAPPING_NOT_APPROVED off the row flags, the outside list removed from the card, FactsForm (`:enter`; matrix through `:enter`) and the "Enter them…" demographics on Delivery-path studies.
- **Removed:** ConfirmGroups and its index.
- **Lists and tails.** The study list on DataTable; the StudiesTab tail removed; product cards absorb Dissolution and the held-back attributes; Populations and Settings rewritten; empty states; "In the model" links.
- **Charts:** sizing and colours.
- **Specs:** delivery.spec (card in Clinical studies, gate line), inputs-data-cards, client-data (`dataset-unpromised`), inputs-sheets-on-arrival.
- **CHANGELOG** entry.

Slice 4 adds batch work, focus and performance (frontend only). Deliverables:
- **Batch tables.** LinkTable (one row per file, suggestions, BulkBar, one reason, one call per destination); NotReadTable (loose numbers grouped by pattern; batch `regions:exclude` per file); MissingValues (batch S0 with one citation).
- **Layouts.** LayoutQueue, with MappingReview in queue mode at the row's version and "Approve all not-data readings".
- **Kit.** Reason with suggestions and a "use last" chip; focus moves to the next row, a live region announces, and Dialog gets a `returnFocus` fallback; aria-labels with context on repeated buttons.
- **Performance and phone.** `useMutation({ invalidate })` scoped to the delivery keys; lazy subject cards; stacked rows on a phone.
- **Specs:** inputs-task-first (focus via route mocks, phone layout); delivery.spec uses `notread-*`.

Slice 5 lets the person fill what is missing (minimal API). Each sub-slice is its own commit with its OpenAPI snapshot, `api-types`, CHANGELOG entry, Python tests and UI:
- (a) registry "empty" rows on Compound, with "+ n more you can fill in";
- (b) `values:assign` `new_arm` / `new_batch` / `new_analyte` / `analyte`, and `study_options.analyte` / `.matrix`, which gives "a new arm…" in LinkTable and "State it…";
- (c) `silent_cells` and scope `cells`, giving the per-cell list and batch in NotReadTable (with the owner's review of the intake-contract change);
- (d) `mappings:propose` and the mapping `vocabulary`, giving the structured layout editor and "Read this table…";
- (e) the requirement-status check for person-entered demographics.

Last, update `docs/CONTINUATION_PACKAGE.md` §4 (§4.1 only if a stage's status changes), and add a row to the CHANGELOG session table.

## Risks

**Join**
- *Risk:* a wrong merge puts a study on the wrong confirm path.
- *Example:* a label collision between two studies whose files differ.
- *Mitigation:*
  - deterministic precedence: dataset, then label, then file (one subject per type in the file);
  - never across types, never two Delivery subjects;
  - aliases always shown, with "Show separately" (localStorage, per viewer);
  - unit-tested on both seeds.
- *If wrong:* the card is still confirmed by the server's own rules. The API refuses a double load (client_api.py:546-580, `loaded_elsewhere`), so a wrong merge costs clarity, not data integrity.

**Hidden legacy confirm**
- *Risk:* on Delivery-path cards the sheet form's quick Confirm sits in the ⋯ menu. While the delivery-wide gate holds, that hidden route is the only way to confirm quickly, so users may miss it.
- *Mitigation:* the gate line says what is left. The ⋯ action says whichever confirmation comes first is what loads.
- *Owner's call:* whether to promote it while gated.

**Science and SME decisions (UI cannot fix)**
- *Delivery-wide gate.* One clean study still waits for all 9 files (§11.10). The UI makes it visible and batchable but cannot remove it; per-subject coverage is an owner decision.
- *Template header cells.* vessel_1… counted as loose numbers is an intake rule (`intake_rules.yaml`, SME, UNVERIFIED v0.1). The UI batches them and demotes them to "Blocks nothing" only where no Delivery confirmation depends on them.
- *Never-landing layouts.* Excretion, product attributes and occasions still need approval although they never reach the model (an acceptance-check decision).
- *Mitigation:* the UI only tags them "kept, not used by the model".

**API slice 5**
- *Coverage counting.* Scope `cells` changes what counts as excluded; it needs the owner's review and a CHANGELOG entry.
- *Matrix and analyte.* Labelling them is science-adjacent.
  - Values come from the API's vocabularies, never typed in the web (CLAUDE.md: never invent names).
  - The person's labels are recorded with their reason in the ledger's audit.
- *Demographics.* If the requirement status does not count person-entered facts, (e) needs a backend fix before the UI ships.

**Part 11 and audit**
- *Batch reason.* One reason is written to several records (one per file or subject).
- *Suggestions.* They only fill the field; the person presses the button. The reason stays required and editable; nothing is auto-submitted.
- *Unchanged:* the step-up flow, `ConfirmDialog` mechanics and signature manifestation (only copy changes); the "UNVERIFIED" marks, kept uppercase.

**Blinding**
- Queue summaries, suggestions (`caption` is null for a blinded file), the "Holds" column and silent-cell text must use WITHHELD.
- Counts must never reveal values.
- The spot check stays refused for blinded studies.
- *Test:* covered in inputs-work.spec with a blinded fixture row.

**Performance**
- *Risk:* the page still reads `/delivery` (692 KB) on open, and the To do list needs subject cards (25-120 KB each).
- *Mitigation:* lazy, idle-time loading with at most 2 at a time; a 60 s cache; mutations that invalidate only the delivery keys (about 850 KB per click becomes about 120 KB).
- *Further gains* need the deferred slim status route and per-file paging (an owner's call).

**Test churn**
- About 14 specs move. The seeded projects are shared, so new interaction tests use route mocks or their own fixtures, never the seeds.
- Each slice updates the specs it moves, keeping CI green.

**Global token change**
- `--warn-ink` and `--control-border` affect every page.
- *Check:* contrast and visual regressions on Review & sign and Run via zz-ux-shots before merge. `--obs` (the chart colour) is not changed.

**Plan deviations**
- Departs from intake-contracts §8.10 (the Delivery section beside ReadingTray) and from 2026-11-03 §3.2 (left rail; "To confirm" at the top of the rail; a files drawer).
- Recorded in the new plan and in the CHANGELOG, as CLAUDE.md requires.
- The "Client data domain" principle of §3.2 (data lands in its home area) is honoured by the cards.

**Scope creep**
- Slices 1-4 are frontend only and each is shippable.
- If the owner wants to start using the page sooner, slices 1-3 alone remove the 6,000 px wall, the duplicate lists and the contradictory states.

## The other two designs (summaries) and the judges

### Study-first Inputs: one card per study, product and compound, with files kept in their own view

The scientist works study by study and product by product, so the page is built the same way. Each study, each product and the compound is exactly one card in its own area, whichever reader found it (Delivery, the legacy sheet reader, the model catalog, the datasets, the proposal). The card holds everything about that subject: the values from either reader, the facts no file states (filled in place with typed controls), what needs a decision, the files and tables it came from, and exactly one confirm button. That button is chosen by `confirm_on`, and the Part 11 step-up stays on the Delivery path. Files and reading mechanics (table layouts, regions, loose numbers, numbers not read, timings, AI reading) move to a secondary "Files" view. One open-items model, computed from both pipelines, counts every item once and gives it one home. It uses four status words everywhere: Missing, To confirm, To decide, Done. Nothing a person can do today is removed: the second reader's path stays reachable from the card's ⋯ menu or "How the files were read", read-only where it would compete.

### Inputs, guided: Client data in five steps, model inputs by domain

Each object has one home and one status. A file is one row. A study, product or set of compound values is one row with one card and one way to confirm it. A value sits on that card. Client data is worked through a short guided flow, Files → Tables → Studies & products → Confirm & sign → Loaded, and each step shows only its own work. Both readers feed that flow as one merged list: the new Delivery reader and the older sheet reader. Once confirmed, the data appears in its domain. The five domains (Compound, Products and dissolution, Clinical studies, Populations and individuals, Simulation settings) show what the model holds and every input a person can still fill. A count appears once: in the rail per area and in the progress header per step. Status uses four words: Missing, To confirm, To decide, Done. Amber appears only where a decision is needed. Repeated decisions of one kind are made in bulk with one reason, and that reason goes to the audit trail. The Part 11 signature, the step-up and blinding are unchanged.

### A judge's verdict

Winner: Task-first Inputs: one "What needs you" list across both readers, with the areas as calm reference

**Graft:**

Keep Task-first's single work model, its slicing (slice 1 = DeliverySection moved unchanged into Client files, plus the CSS fixes) and its testid plan. Graft the following.

From Study-first:
1. **Join.** Auto-merge only on loaded_elsewhere dataset ids or an exact normalised label. A prefix alias on a shared file (230-23-REF and 230-23-TEST beside 230-23) becomes a person-answered To decide item: "Same study as 230-23?". Yes pre-fills the Link bar with study 230-23, arm Reference/Test (new) and a file-name reason. Drop Task-first's rule 3 silent post-link merge.
2. **One place to act.** In To do, act inline only on file-level and batch work: layouts, link, numbers not read, Ask the client, the S0 batch. Subject-level facts, disagreements and checks are To do rows that open the card item, with the review bar. This applies Study-first's 'one home' and stops the same form appearing twice.
3. **StudyCard anatomy**, in this order:
   - "To do on this study";
   - a two-column typed Facts grid, where the sheet reader's draft answers become suggestion chips ("the sheet reader's answer: 50 mg", "6 subject columns 001–006");
   - Observed data;
   - Files and tables;
   - "Suggested for this study" (unlinked files whose caption or name points here, with a checkbox, a suggested arm and one reason);
   - Checks;
   - Not loaded with this study;
   - one Confirm;
   - "How the files were read".
4. **Subject merge.** POST /delivery/subjects/{type}/{subject}:merge {into, why}, wrapping ledger_entities.merge (:281), with "Same as…". This is the only fix for later-file-never-joins; Task-first defers it.
5. **Compound parameter slots.** Use pbpk_domain.parameters.model_ids()/reference_ids(). Show a slot with no req_id as "not in this project's data plan → Start" instead of omitting it.
6. **"Only what needs me" filter**, applied to Client files too.
7. **Populations.** Studies that share an individual sit on one line, and a patient study on the healthy default is flagged.
8. **Accessibility and layout.** A skip link to the areas, and the ValueSource sr-only role text with a distinct value-cell outline. Optionally, at 1100 px and wider, the plan §3.2 left rail, with To do as its first item (the plan's "To confirm (n)" at the top of the rail) and Client files under a divider.

From Guided:
1. **"Done" as Step 5 Loaded.** Merge Step 5 into Task-first's "Done" group and its "In the model" link target. Per subject, show:
   - signed by and when, with the manifestation;
   - what loaded (1 dataset · 13 values);
   - where it now lives (link);
   - the held items;
   - "Changed since signed: confirm again".
   Add "Available downstream" (studies by role, products with a release model, compound values kept).
2. **Fewer refetches.** Write the DeliveryPage that values:assign and regions:exclude already return into the cache with setQueryData, instead of refetching. Add the test budget: at most 2 requests and under 100 KB per decision click.
3. **Layout rows.** Each row expands to one-line column summaries ("time ← 'Time (h)' · concentration ← 'Conc (ng/mL)'"). Keep per-row review for real layouts. Allow bulk approval only for 'not data' readings, and write "approved with N other layouts" into each note.
4. **Typed vocabularies.** `conditions` (apparatus, medium, pH, rpm, volume) on the assign/label call for DISSOLUTION_METHOD_INCOMPLETE, and study_options.matrix harvested from modeler_intake.fields.
5. **URL state.** Put the area and the To do filter in the URL, so Back and shared links work.
6. **"Could not be read" section** in Client files, with a remedy per file (text PDF, digitize, mark as not data).
7. **Context aria-labels** on repeated buttons, e.g. "Assign the 76 values of 230-23 Fasting Reference.xlsx".

Do not take Guided's premise that the e2e suite runs the legacy reader. config.py:55 defaults to 'both'. Sheet-form specs must reach SheetReader from the Client files row in 'both' mode.

**Missing from all three:**

1. **No way to undo or change a decision.**
   - "Mark as not data" is one-way: intake_review.py has only exclude_regions (:745), and delivery_routes.py:1396-1413 has no restore route.
   - No UI re-links values that were linked to the wrong study or arm.
   - All three designs add bulk actions (45 cells, several files, N layouts per click), so a mistake now costs more.
   - Needed: "Change…/Restore with a reason" (a regions:restore route, and re-assign surfaced on the file row) plus a per-delivery decision history.
2. **No decision log for the signer.** Before "Confirm and sign", the Part 11 signer cannot see what was linked, excluded, approved or overridden, by whom and with which reason. This matters most when one bulk reason was written to many records.
3. **Plan 2026-11-03 §3.2 items that none of the designs carry:**
   - the search box over labels, ids, values and sources;
   - the filters 'from the client', 'from the literature' and 'conflicts';
   - Clinical studies grouped by kind (IV, oral fasted, fed, multiple dose, DDI, special populations): the owner said "uncategorized", yet all three sort only by status;
   - the client's compound value sitting in its parameter row beside the literature, marked To confirm (all three put it in a separate card or a pointer).
4. **The 692 KB /delivery payload and the 3 s full poll stay.** Task-first and Study-first defer the slim status route and per-file paging of the unassigned values. Guided keeps the poll. Daily use on the server stays heavy (about 14 MB a minute while a file is read), and every lazy subject card (25–120 KB) adds to it.
5. **No handling of shared, concurrent work.** The seeded projects are shared, and the cards are cached with a 30–60 s staleTime. No design says what happens when another reviewer settles an item first: stale counts, a stale "Next", or 409s on a decision already made.
6. **Blinded subjects in the work flow.** No design says whether Next and the counts skip a blinded subject's items that cannot be acted on, or how they count them. As written, Next can land on a dead end.
7. **No end-to-end acceptance test of the owner's job.** No design proves on a cloned seed (the shared seeds must not be touched) that a scientist can take exampleamide from the uploaded files to 230-23 linked (Reference/Test arms), facts filled, gate cleared, signed and visible "In the model". The tests check layout, counts and testids, not that the job can be finished.
8. **No interim for the owner-only gate decisions.** None quantifies the per-delivery gate (contracts §11.10), the template header cells or the never-landing layouts for the owner. A preview such as "with a per-subject gate, 231-24 would be ready now" would let them decide quickly, instead of the decision sitting under Risks.

### A judge's verdict

Winner: Task-first Inputs: one "What needs you" list across both readers, with the areas as calm reference

**Graft:**

From Study-first (B):
(1) One home per decision. Subject-level To do rows (facts, disagreements, link questions, confirm) become navigation rows that open the card. They must not render a second inline form. To do keeps inline forms only for file-level batch work: layouts, LinkTable, NotReadTable, Ask the client and the S0 batch.
(2) Replace A's per-area 'Open here' strip with B's one-line area head ('9 studies · 4 to confirm · 3 to decide · 2 files not linked') and B's area-level gate line ('Delivery studies can be confirmed once the delivery is cleaned up… → To do').
(3) B's conservative join. Merge automatically only on a loaded_elsewhere dataset id or an exact normalized label. A prefix alias (230-23-REF / 230-23-TEST beside 230-23) becomes a 'Same study as 230-23?' To decide item. Yes pre-fills the Link row with study 230-23 and the suggested arm. Drop A's rule-4 file+sheet attach, or run it only once the cards are loaded.
(4) The 'Only what needs me' filter applies to every area and to Client files; it keeps the to-confirm testid.
(5) The Facts grid shows the sheet reader's draft answers as suggestion chips on Delivery-path cards.
(6) In the model: the StudiesTable shows greyed 'loads when confirmed' rows for studies awaiting confirmation.
(7) A skip link to the input areas.
(8) The :merge route (POST /delivery/subjects/{type}/{subject}:merge) for later-file-never-joins.

From Guided (C):
(1) Make A's 'Done' group and its 'In the model' status a real 'Loaded / Available downstream' view. Per subject it shows who signed and when, what was loaded (datasets, values, dissolution records), where it is now (Clinical studies → 230-23 · role S2), the held items, and 'Changed since signed → confirm again'.
(2) Write decision responses into the query cache with setQueryData (values:assign and regions:exclude already return the page), and assert at most 2 requests and under 100 KB per decision click.
(3) A separate POST /delivery/values:label {targets, analyte|new_analyte, matrix, arm|new_arm, batch|new_batch, conditions, why} for 'State it…'. CL-01's values already have a study, and DeliveryAssignment clears the arm when it is omitted, so overloading values:assign is wrong for relabelling.
(4) Bulk layout approval: rows expanded to their column summary, one required note, and N audit entries 'approved with N other layouts'. The per-row review queue stays the default.
(5) The `[data-subject=…]` count == 1 assertion.
(6) The 'what is missing → where → how' table as the spec for To do › Fill in.
(7) For API 1, build the compound 'empty' rows from RequirementMatrix items. Show placeholder targets (elim.fm.<enzyme>) as read-only 'add through a pathway' rows, never as ids invented from the registry.
(8) study_options.matrix harvested from modeler_intake.fields.

**Missing from all three:**

(1) Arm collision ordering. Every design ships the bulk Link UI, pre-filled with the suggestion '230-23' for both the Reference and Test files, before the new_arm API. Both files label rows 'subject 001 · period I', so linking both to 230-23 without an arm creates the very conflict whose 'keep one' throws away an arm of the BE comparison. Either guard it in the frontend (refuse to link two files whose label keys collide to one study without distinct arms) or ship new_arm together with LinkTable.
(2) No working path to the model while the gate holds. Delivery-path subjects on exampleamide cannot be signed until the delivery-wide gate clears. Its 72 numbers not read sit in data tables, and the only remedy before the cells-scope API is discarding the table. All three ship that API last, and A/B tuck the quick legacy confirm into a ⋯ menu while C collapses it. Through slices 1-4 the owner therefore has no visible path to put 230-23 or 231-24 into the model. While gated, surface the legacy confirm as the primary action (with the 'loads once' warning), or bring the cells scope forward.
(3) No server-side join. The reliable link between the two readers (the legacy group id per DeliverySubjectRow, from the legacy_overlap the API already computes) is left to browser heuristics. DeliverySubjectRow carries file shas but no sheet, so any sheet-level join needs every subject card fetched.
(4) Spec gaps.
   - client-documents.spec.ts:49-50 uses the inputs-files button and inputs-files-drawer, which all three delete; no plan lists it.
   - B and C keep `read-agent-*` while hiding agent buttons with AI off, which breaks studies-client-sheets.spec.ts:41.
   - Pure-TS model specs in Playwright are a new pattern: package.json has no vitest or jest, and no e2e spec imports lib/.
(5) Counts and payload. The 692 KB /delivery payload and its full-ledger 3 s poll stay. All three add lazy subject-card fetches (9 × 25-120 KB) just to compute badge counts, so counts are wrong on first paint. Per-subject open counts on DeliverySubjectRow, or a slim status route, would fix both and is an additive, unlocked change.
(6) Joining a later file to a person-named study. No design fixes ledger_entities.py:246-251 (resolve() step 4 should accept person-named studies as join candidates); B only adds a manual merge.
(7) No undo. None says how to reverse a bulk decision (un-mark 45 cells as not data, unlink a file) or what the audit trail shows for the reversal. Batch actions with one reason need a visible undo path.
