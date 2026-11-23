# User Flows (Phase 3, Gate 2)

Each flow lists the pages (P-xx, see [`PAGE_INVENTORY.md`](PAGE_INVENTORY.md)), the decision points and the API
calls. ✎ marks a write, 🔏 a Part 11 signature (step-up, never a password typed into Modeler One). Flows keep every
capability that exists today; changes from today are marked **Δ**.

## F1 · From proposal to a signed plan and a campaign (the owner, a curator)
1. **P-01 Home** → Create project → **P-04**. Drop the proposal and the client's files, check each file's tag.
   ✎ `POST /projects:initiate`. Lands on **P-11 Start**.
2. **P-11 Start**: the agent's drafts wait on the person (marked). Set the missing fields. ✎ `PUT /brief`.
   Side nav: Start turns ✓ when nothing waits. **Δ** "Continue to Data" is the header's primary action.
3. **P-12 Data room**: Upload the delivery (or "Import the files already added"), Run. Watch the run status line.
   Work the sections, conflicts first; open a source chip in the split panel; decide; enter missing values; write the
   data requests. 🔏 Send to the model (step-up).
4. **P-13 Inputs**: To do lists what remains for the model, under the four status words. Fill in, link, confirm each
   study or product card; 🔏 sign the confirmation. Status line: "In the model: n studies · n formulations ·
   n compound values".
5. **P-14 Review & sign**: check study roles on the canvas, estimation and validation plans, credibility (risk tier,
   acceptance criteria, stage budgets); the validator shows no open rule violation. 🔏 Approve and sign the MAP.
6. **P-15 Campaigns** (Run): readiness is met → ✎ Run campaign → **P-16 Campaign**.
7. **P-16**: Stages, Fit and Rounds fill in as the campaign runs. If not on PK-Sim, the fixture banner stays on top.
8. At S7: **Package** tab shows the reproduction verdict and hashes; download the package when exportable.

Decision points: step not ready (side nav ● and the page's readiness list); API unreachable (flash bar, nothing stale
shown as current); a refused write (`NOT_OWNER`, `STEP_UP_REQUIRED`, `STEP_UP_STALE`) answered in words in the flash bar.

## F2 · A client delivery arrives (owner)
1. Any project page → side nav **Data → Data room** → Upload a delivery. ✎ `POST dataroom/uploads`, `POST dataroom/run`.
2. Run status: files read, OCR pages, steps waiting for an AI model. If a model cannot answer, the failover chain
   moves on (admin-set); the run line says which model answered.
3. **Overview** section: question card (confirm or edit ✎ `PUT dataroom/question`), counters, "Needs attention first".
4. Each section: findings with source chips → split panel (page image with the box, or sheet lines).
5. Decisions ✎ `POST dataroom/decisions/{id}`; entered values ✎ `POST dataroom/entered`.
6. Data requests: edit ✎ `PATCH dataroom/requests/{id}`, print or copy for the client.
7. 🔏 Send to the model: `GET publication` (preview) → `POST publish`. Confirmed inputs reach evidence and datasets,
   which **P-13 Inputs** reads.
8. **Open (G1-1):** which send is the official one, Data room publish or the Inputs signed confirmation. Until
   decided both stay, and each page says what it sends and where.

## F3 · A reviewer signs across several projects
1. Top bar **Your work (n)** → **P-02**: filter "To sign". Rows: "Sign the MAP · Project A", "Decide the S1
   escalation · Project B".
2. Open → **P-14 Review & sign** of project A (read-only for edits; Sign is enabled because a reviewer the project is
   shared with may sign). 🔏 `POST plan:sign`.
3. Back to Your work (browser back or top bar); the row is gone after the next read.
4. Open → **P-16 Campaign** of project B; the escalation dialog opens from the flash bar. 🔏 `escalation:resolve`.
**Δ** Today the reviewer finds these by opening each project, or by the global pop-up. Nothing is decided in the list.

## F4 · A campaign escalates
1. The stage cannot proceed (rounds or budget spent, a parameter at a bound, no permitted action).
2. Everyone who may sign that project sees: a flash bar on the project's pages, a ● on Run in its side nav, an item
   in Your work. **Δ** People who are not members see nothing (today `GET /escalations` is company-wide, R-S01).
3. Dialog: the diagnosis in words, the permitted actions (retry, accept the best so far, abort; at S5 learn or new
   evidence), a note. 🔏 Decide. Refusals (already decided, gate not met) are answered in words.

## F5 · A colleague the project is shared with reads it
1. **P-03 Projects** shows the project with its owner's name.
2. Every project page shows the flash "Shared with you to read. Only the owner, NAME, changes it." and no edit
   controls. **Δ** Today the buttons show and the API refuses with `NOT_OWNER`.
3. A viewer opens **P-14 Review & sign**: read through `plan:view`. **Δ** Today a 403 (`GET /plan` needs a writer).

## F6 · Change something after signing (owner)
1. On P-11, P-13 or P-14, edit a value that a signed artifact depends on.
2. **Δ New:** before saving, "What this changes" lists the artifacts that become out of date (`POST /impact`).
3. Save ✎. History → Out of date lists them; the side nav marks the affected step ●.
4. On P-14, a move after the MAP is signed is a MAP deviation (banner, reason required); re-sign 🔏.
5. **Δ New:** a moved study can go "Back to the MS-01 default" (`:unlock`).

## F7 · External validation fails (S5)
1. **P-16 → Feedback** tab: the failing studies, the cycle count against its cap.
2. Decide 🔏: limitation (accept the best), learn (move studies, a reason beyond the cap), new evidence (parameter,
   value, unit, source), or stop. `escalation:resolve` with the S5 payload.

## F8 · The platform owner rotates a provider key
1. Side nav **Admin console → Keys** (**P-28**): the old key is flagged (> 90 days).
2. Add key (write-only field) ✎ 🔏 step-up → Test → Activate (the previous one retires) → audit event on the
   owner's chain. No restart.

## F9 · The platform owner adds a person to a company and gives them projects
1. **P-25 People** → Add person: company, roles (viewer, curator, reviewer, QA) ✎ 🔏. Keycloak sends the set-password
   email, or the owner sets a temporary password in Keycloak's own console (never in Modeler One).
2. **P-24b Company** → Give a person projects (after they have signed in once) ✎ 🔏.
3. **Open (R-S05):** QA can be given today but grants nothing. Proposed: QA reads every project of its company.

## F10 · Something is not working
1. A page cannot read the API: the flash bar says so in words; the top bar dot turns grey; nothing shown is called
   current.
2. The platform owner opens **P-32 System status**: API health, execution backend, each agent's model and key state,
   the intake pipeline. **Δ New** page on existing reads.
