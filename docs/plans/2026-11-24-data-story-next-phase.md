# The data story, next phase: right data per question, runs that never waste work, and the Claude credit

**Status:** PROPOSAL for the owner's review (2026-11-24). Nothing below §1 is built yet. Each section ends with what
needs your decision; §11 lists them all in one place.

**What it answers:** your message of 2026-11-24:
- the four open gaps in the data story;
- the $100 Anthropic credit (costs, budgeting, the "identity federation or API key" screen);
- switching models from the admin page;
- runs that keep going and resume from where they stopped;
- memory and lower LLM cost;
- extracting only what each application needs;
- a literature review for new features;
- the whole path from upload to a MAP a person reviews.

**How it was built:**
- Four literature reviews, run in parallel: about 1,200 records screened and about 330 cited. Full reports with
  references are in `docs/research/2026-11-24-*.md`.
- The token counts of our own stored runs.
- The current code.
- Anthropic's price list as of 2026-11-03, from the API reference.

---

## 1. Done today (in this commit, not waiting for review)

| Item | What changed | Measured |
|---|---|---|
| **"The campaigns could not be read (HTTP 500)"** | One campaign stored by an earlier build carried a key today's record no longer has, and that one record failed the whole list. Now the unknown key is left out (nothing is written back to the stored record). A campaign that still cannot be read is named on the dashboard with the reason, and the rest are shown and counted. Escalations are read the same way. | API tests and the dashboard e2e pass. |
| **Gap 3: merged spreadsheet title cells** | A title merged across a sheet is kept once, in its first cell. It used to appear 17 times on one line. A header merged over its columns (e.g. "Nominal time (h)") keeps its copies, because it labels each column. | Novaprazole listing: the 3 title lines now read once. |
| **Gap 1: a single-arm study and its product** | An arm's product is found in this order: the product its fact names; the card's only product of the role it names; its own words (e.g. "clinical formulation" against "commercial formulation"); its batch number; the card's only product. A single-arm study's one arm covers each treatment in the data, such as a multiple-dose study's days. **The page says how each arm was tied.** If no document names the product and the card has two, the room **asks** (it never guesses). | Quorafen: arm product, role (reference) and plan (calibration, N = 10) are now right; before, they were missing, wrong and N = 0. |
| **Gap 4: the question stage (A6) took 2 to 9 minutes** | Code now builds a short digest of the delivery before A6 starts: every file, its parts, and the lines that may state the question, the products or the design, quotable as written. A6 writes the card from this digest first, with no file tools. The tools come back only if no card can be saved. | Before: every run used all 14 turns, 117 to 560 s, and 16 to 31 % of the delivery's input tokens. After: see §1.1. |
| **Gap 2: "0.1 N HCl" read as a pH** | **Not built: it needs your choice (§9).** | — |

### 1.1 A6 after the change

Measured with Nemotron Ultra on NVIDIA's free tier, one delivery at a time. The "before" figures are the stored runs of
the same deliveries.

| Delivery | Turns | Input tokens | Output tokens | Time | Card |
|---|---|---|---|---|---|
| Novaprazole | 2 (was 14) | 16 k (was 204 k, −92 %) | 4 k (was 12 k) | 97 s (was 117–139 s) | products, roles and regulator right |
| Zelitrex | 3 (was 14) | 24 k (was 346 k, −93 %) | 11 k (was 16 k) | 230 s (was 175–312 s) | products and roles right |
| Quorafen | 3 (was 14) | 26 k (was 156 k, −84 %) | 12 k (was 10 k) | 210 s (was 134–560 s) | products, roles and regulator right |

**Reading it:**
- **Cost:** −84 to −93 % of A6's input, the largest stage after extraction.
- **Time:** the worst cases are gone. What is left is the time the free model takes to write a card of about 11,000
  output tokens (two submissions when code refuses a quote). A shorter card is the next lever. On Claude, output is
  several times faster.

---

## 2. The $100 Claude credit

### 2.1 The screen you saw: "With identity federation, you don't need an API key"

The Console offers two ways for our server to prove it may use your account:

- **API key.** A long secret string the server sends with every request. It works from any machine. It is a password:
  if it leaks, anyone can spend your credit until you revoke it.
- **Identity federation.** No stored secret. The server shows a short-lived identity token issued by an identity
  provider that Anthropic trusts, and Anthropic trades it for temporary access. The token comes from a cloud platform
  (AWS, Google Cloud, Azure), GitHub Actions or Kubernetes. For this to work, Anthropic must be able to reach and check
  that provider's public signing keys.

**Recommendation: "Continue with an API key".**
- Our server is a machine on your own network. It has no cloud identity, and our Keycloak is not reachable from the
  internet, so federation has nothing to verify.
- Federation is worth revisiting if the platform later runs on AWS, Google Cloud or Azure.

To make the key safe:
1. In the Console, create a **workspace** for Modeler One and create the key inside it. A key belongs to one workspace.
2. **Set a spend limit on that workspace**, for example $90, so the Console stops requests before the credit is gone.
   Check where your Console offers this. If it does not, the in-app cap in §2.4 does the same job.
3. Put the key on the server only, the same way as the GroqCloud and NVIDIA keys (Admin → Keys, guide §6b). Never put it
   in a chat, an email or the repository.
4. If it ever leaks, revoke it in the Console and create a new one.

### 2.2 What a delivery costs (estimates, with the basis shown)

**Measured on our three made-up deliveries** (8 to 11 files each, full run A6 to A10, counted by Nemotron's
tokenizer; Claude's counts will differ somewhat):

| Delivery | Model calls | Input tokens | Output tokens |
|---|---|---|---|
| Novaprazole | 102 | 0.81 M | 131 k |
| Zelitrex | 100 | 1.13 M | 111 k |
| Quorafen | 84 | 0.51 M | 93 k |

**Prices** (Anthropic list prices, per million tokens; cache reads are what a repeated prefix costs):

| Model | Input | Output | Cache read |
|---|---|---|---|
| Claude Opus 5.5 | $4 | $20 | $0.20 |
| Claude Sonnet 5.5 | $2 | $10 | $0.10 |
| Claude Haiku 5.5 | $0.10 | $0.50 | — |

A cache write costs 1.25 × input. The Batch API halves the price but takes up to 24 h, so it is for evaluations, not
live runs.

**Estimated cost of one delivery of about 10 files:**
- We assume output × 1.5, because Claude's thinking counts as output.
- We assume about 70 % of input is read from the cache, since the conversation is cached at every turn (already on).

| Model | No cache | With cache | After the A6 fix and a cache-friendly prompt order (§5) |
|---|---|---|---|
| Opus 5.5 | $5–8 | $3.5–5.5 | **≈ $3–4.5** |
| Sonnet 5.5 | $2.5–4 | $1.8–2.8 | **≈ $1.5–2.3** |
| Haiku 5.5 | $0.15–0.3 | — | **≈ $0.2** (its accuracy on our tables is unknown) |

**A real client delivery is bigger.** At 40 to 60 files, expect about 4 to 6 times more:
- Opus about $15–25;
- Sonnet about $8–14.

**These are estimates.** The first real Claude run must measure the true figure. The Admin → Usage page already prices
each run.

### 2.3 How to spend the $100

The cost that matters is **cost per correct input value**: a run on a free model that you then fix by hand costs more of
a modeller's hour than a few dollars of Claude.

| Use | Model | Budget | How |
|---|---|---|---|
| Development and every test | free (NVIDIA, Groq) and the in-house model | **$0** | Claude is never used for testing (your rule). |
| **One calibration run** | Claude on a made-up 10-file delivery | **≈ $5** | Measures the real cost per delivery and Claude's accuracy against our answer key. It doubles as the rehearsal of demo 1. **Needs your yes.** |
| **3–4 demos** | Sonnet 5.5 for A6, A7 and A10; Opus 5.5 for A8 (extraction); a different model for A9 (the second opinion) | **≈ $15–20** | Each demo delivery is run once on Claude and stored. Showing it again **replays the stored run at $0**. A live run in front of the audience costs about $4–5. |
| **The real project** | the same split | **≈ $60–70** reserved | Enough for a 40 to 60-file delivery and a re-run of the files a modeller sends back. |
| Margin | — | ≈ $5–10 | — |

**If you later add your own money:**
- Opus 5.5 is worth it for extraction (A8), where its accuracy decides how many values a modeller must fix.
- Sonnet 5.5 is enough for the question card, triage and the report text.

The calibration run tells us whether that split holds.

### 2.4 Guards so the credit cannot run away

1. **Console workspace spend limit** (§2.1).
2. **In-app hard cap for paid providers only (needs your approval).** Today the monthly limits only warn and never stop
   an agent (your answer of 2026-11-10). I propose a change for **paid** models only:
   - a per-run and per-month dollar cap;
   - reaching it **pauses** the run, it does not fail it (§4), and says why;
   - you raise the cap or switch to a free model, and the run continues from where it stopped.

   Free and in-house models keep today's warn-only rule.
3. **Estimate before running.** Before a paid run, the Data room shows the expected cost from the file count and sizes,
   and asks once.
4. **Client permission.** Anthropic is a cloud service like NVIDIA and Groq. A client's files go to it only when that
   project's "Where the files may go" panel records the client's written permission. Made-up demo deliveries need none.

**Decisions:** D1 (API key), D2 (calibration run), D3 (hard cap for paid models), D6 (client permission rule).

---

## 3. Switching models from the admin page

**What exists today** (Admin → Models):
- one form switches **every agent** to one provider and model at once, with its effort and a fallback;
- each agent can also be set on its own;
- the failover chain moves to the next model when one is unavailable.

**What to add:**
1. **A direct Anthropic provider.**
   - Today the Claude client talks to Claude **on Amazon Bedrock** only, so your Console key cannot be used.
   - Adding the direct Claude API is a small change: the SDK is already installed, and caching and effort are already in
     the client.
   - It uses the server-side refusal fallback the direct API offers.
2. **Presets, one click each, with a reason recorded:**
   - **"Free"**: NVIDIA and Groq, behind the in-house model;
   - **"In-house only"**: no cloud;
   - **"Claude demo"**: the §2.3 split;
   - **"Claude, all Opus"**.

   The page shows the estimated cost per delivery next to each preset.
3. **Switch during a run.** A switch applies from the next step; a paused run resumes on the new model (§4). It already
   applies "from the next request". What is missing is resuming a stopped run.
4. **Per-project override** (later, if you want it): e.g. the demo project on Claude while every other project stays
   free.

**Decision:** none needed, unless you do not want item 4.

---

## 4. Runs that keep going, and resume where they stopped

**What exists:**
- Each finished piece of work is stored as it finishes: a file's triage, a file's extraction, a file's check, the
  question card.
- "Run again" redoes **only what is missing**. A rerun never pays twice for a finished file.
- A model that answers HTTP 429 three times rests for 10 minutes.
- The failover chain tries the next model.

**What is missing:**

| Gap | Today | Proposed |
|---|---|---|
| The run stops for a reason that passes (quota, 429, 5xx, budget cap) | the stage ends with "no card (LLM_UNAVAILABLE…)" and the run says **failed** | the run is **paused**, with the reason and the time it will try again |
| Nobody restarts it | a person must press "Run again" | the server **resumes it by itself** after the rest (10, then 20, then 40 minutes), or at once when the admin switches the model or adds a key |
| Where it stopped is not said | "The run stopped" | "Paused at extraction: 7 of 11 files done. Continues by itself at 14:20, or when you switch the model. Nothing finished is read again." Plus **Resume now** |
| Failover in the middle of a step | the next model continues the same conversation | the next model **restarts that one step** (one file, one stage). A step is short (≤ 10 turns). One model writes each stored answer, which provenance and the audit trail need, and Claude's thinking is tied to the model that wrote it. |
| A crash in the middle of writing | a half-written file is possible | write-then-rename for every stored answer |

**Not proposed:** resuming inside a step, turn by turn. Steps are short, so restarting one costs a few cents at most. A
mid-conversation resume on another model is not valid for Claude 5.5 (its thinking is bound to the model and the
conversation).

**Decision:** none, unless you disagree with "restart the step, not the conversation".

---

## 5. Memory and lower cost

Ranked by value. "Measured" means measured in the cited study on its own work; "estimate" means ours.

| # | What | Saving | Risk and how it is handled |
|---|---|---|---|
| 1 | **A6 digest** (done today) | A6 was 16–31 % of input tokens and 2 to 9 minutes | — |
| 2 | **Exact answer cache, by content.** Key: file hash + stage + prompt version + model + effort + reader version + tenant. A file already read the same way is not read again. | 100 % of a repeated call. A demo replay, a re-sent file or a rerun after a fix to another file all cost $0 | A missing version in the key would reuse a stale answer, so every version is in it. **Never** reused across clients. Never "similar" matches, only identical ones. |
| 3 | **Prompt order that the cache can reuse across files.** Same instructions and tools first, the delivery's block next, the file last. Today each file starts its own cache. | Estimate: −60–75 % of input spend, about −20–25 % of the total. Anthropic measured 83–86 % off a triage agent | The cache works only for identical leading text, so nothing variable (dates, ids) goes before the file. |
| 4 | **Re-run only failed files at higher effort.** A first pass at lower effort; files that fail code's checks are re-read at higher effort or on a stronger model | Measured by Anthropic: about 40 % below running everything at high effort, with the same pass rate | Code's checks catch wrong values, **not** missing ones; omission has its own guard (§6.4). |
| 5 | **Effort per agent**, chosen on our answer keys | Measured: 33–50 % less at low effort for 1–3 points of accuracy; another benchmark lost 13 points | Swept on free models first; Claude only in the calibration run. |
| 6 | **Cheap model for triage (A7)** | Haiku costs 1/40 of Opus | Only after the evaluation shows it misses no file. |
| 7 | **Project memory (hints, not facts).** Confirmed client conventions: their BLQ and missing markers, decimal mark, treatment codes ("A = reference"), date format. Confirmed table layouts of a recurring CRO template. Decisions with reasons. Data requests and replies. "File X has nothing needed". | Fewer turns on the second delivery from the same client | Injected as a short note (about 300 tokens); **code re-checks everything a hint suggests**; never shared across clients; never a number outside the CPF. |

**Not proposed:**
- **A vector database ("RAG") for client files.** Code already picks the pages each agent reads and gives it a search
  tool.
- **Context compaction.** Our steps are short.

The literature's main finding is that the costly LLM error in extraction is **omission** (60–74 % of errors), then
**misallocation** (a right number in the wrong field, 57 % in the largest study). Neither is a hallucination. Retrieval
that misses a page turns directly into an omission. Money is better spent on §6.4.

**Decision:** none for 1–6. Item 7 (memory) is optional.

---

## 6. Extract what the question needs: requirements by application

### 6.1 The problem you described, confirmed in the code

- A6 writes the checklist itself, from one fixed list. The list includes "manufacturing process and its changes" for
  every project.
- The platform already has **requirement templates per application**: DDI, first in human, food effect, special
  populations, virtual BE, and the small-molecule core. These are locked and SME-governed, **UNVERIFIED**.
- **The Data room does not use them.** So a fasted study's project is asked for fed data, and every project is asked for
  the manufacturing process.

### 6.2 What the literature says

Sources: the regulatory and PBBM reviews in `docs/research/`.

- **Whether an item is needed depends on three things:**
  - the application (context of use);
  - the **compound's properties**: weak base, BCS class, fraction metabolised by one enzyme, renal excretion,
    transporter substrate;
  - the **model's risk**: how much the decision rests on it, and what a wrong decision costs.

  It does not depend on the application alone. Example: fed data is *not* automatically irrelevant to a paediatric
  question. For infants fed milk, for food vehicles, or for a drug with an adult food effect, it matters.
- **Formulation inputs that change predictions:**
  - dissolution per batch and medium, with the method;
  - solubility versus pH, with the final pH;
  - biorelevant solubility;
  - pKa;
  - salt and solid form;
  - particle size per batch;
  - dose;
  - permeability **with the lab's calibration set**;
  - precipitation, for weak bases;
  - the amounts of **functional** excipients only: sugar alcohols, surfactants, pH modifiers, polymers;
  - disintegration.
- **Context only** (stored, never an input; they act only through dissolution and disintegration):
  - the manufacturing process;
  - tablet hardness;
  - the full excipient list;
  - f2.
- **Regulators' top reasons for rejecting a model** (EMA reviewed 2022–23 applications and qualified 28 % of uses): no
  relevant verification data, missing mechanisms, unjustified inputs, poor prediction. **Missing data is the leading
  cause, not software.**

### 6.3 Proposal

1. **Each item gets one status per application:**
   - **Required**;
   - **Usually needed** (becomes required when the model carries high weight);
   - **Conditional**, with a **trigger code computes** from the compound (for example "weak base with a pKa above 5 and
     solubility falling between pH 1–2 and 6.5" switches on the precipitation data);
   - **Optional**;
   - **Not needed**.
2. **"Missing" is shown only for what this question requires.**
   - A conditional item appears only when its trigger fires.
   - "Not needed" items are listed once, folded, under **"Not needed for this question, and why"**.
   - A modeller who wants one anyway turns it on, with a reason (audited).
3. **The confirmed question card picks the template(s).** Several can combine, e.g. virtual BE plus food effect. The
   checklist A6 proposes is then **checked against the template**: it can add items, but cannot drop a required one
   without a reason.
4. **The extractor reads what the selected templates name.** Context-only material is kept as context, so it never
   raises an error.
5. **Each missing required item becomes a data request** with why it matters and **the accepted alternatives**. Example:
   "No IV data: an oral solution, single and multiple ascending dose, mass balance or a population PK model can stand in".
6. **The templates stay SME-governed.**
   - I draft the item tables from the literature as **drafts** (`requirement_drafts`, the existing place), marked
     UNVERIFIED, each item with its sources.
   - They become templates only through the locked-file change, with your approval and a version bump.
   - Until then the Data room uses them as drafts, labelled as such on the page.

### 6.4 Guarding against omission

The literature's main error. Per checklist item, the room keeps a **coverage ledger**: found (where), missing (which
pages were searched), or not needed (why). A required item is never silently absent: it is either found or listed as
missing with what was searched.

**Decisions:** D5 (draft the requirement tables from the literature for SME review).

---

## 7. From upload to a MAP a person reviews: the whole path

**Today the Data room does:**
1. **Read**: code, OCR for scans.
2. **Question card**: A6, which a person confirms.
3. **Triage**: A7.
4. **Extraction**: A8, with code checking every value.
5. **Second opinion**: A9, with one loop back to A8.
6. **Assembly**: code builds analysis sets, means, NCA against the client's own, dissolution, solubility, the plan and
   the PK-Sim input sheet.
7. **Report text**: A10.
8. **Decisions and data requests.**
9. **Send to the model.**

**What is not yet proven:** that "Send to the model" carries everything into Inputs, and on to the MAP draft, without a
person typing again what the delivery already said.

**Proposed:**
- **One end-to-end walk** on a made-up delivery, on free models: upload → Data room → Inputs → plan → MAP draft →
  review.
- Each place a person must re-enter something the delivery already stated is recorded and fixed.
- The walk becomes an e2e test, so it stays fixed.
- Then **the same walk on a real delivery** with the server's in-house model. The calibration run on Claude (§2.3) comes
  last.

---

## 8. New features the literature points to

Ranked by value to Modeler One's goal: a reviewable model package from a client's delivery. The **source** column names
the review in `docs/research/` that supports each feature.

| # | Feature | Why | Source | Size |
|---|---|---|---|---|
| 1 | **Requirements by application, with triggers** (§6) | removes false "missing" and finds the real gaps | regulatory, PBBM | L |
| 2 | **Coverage ledger** (§6.4) | omission is the main LLM error | AI | S |
| 3 | **The client's NCA reproduced, with its method found.** We already compare linear and log-down, and actual times. Add the BLQ rule and the λz window, and report which settings reproduce the client. Proposed tiers: ≤ 1 % same settings; 1–5 % "a setting differs"; > 5 % "the data differ, ask" (**tiers need SME approval**) | explains every difference with the sponsor's numbers | clinical PK | M |
| 4 | **Exclusions flagged, never deleted.** Pre-dose concentration > 5 % of Cmax; vomiting within 2 × median Tmax (immediate release); > 20 % of AUC extrapolated; samples outside the protocol window. Each flag has its reason; **thresholds are SME-governed** | regulators expect the sponsor's population with flags, not deletions | clinical PK | M |
| 5 | **Observed data that know their statistic:** arithmetic or geometric mean, or median; SD, CV or SEM; n per time point. Compared with the same statistic from the simulation | an arithmetic mean compared with a simulated geometric mean is a silent error | clinical PK | S |
| 6 | **Permeability guard.** A raw Caco-2 or PAMPA value is never put in PK-Sim's intestinal permeability. The lab's reference compounds are required, or the value is labelled "fitted" | the scales differ by about 100 ×, and each lab needs its own calibration | PBBM | S |
| 7 | **Dissolution checks:** number of units; f2 preconditions; plateau below 100 % or a bell shape; a disintegration lag; the same method across batches; the reference product tested | the top PBBM rejection reasons | PBBM | M |
| 8 | **Which step limits absorption.** Dose number and sink index from the dose, solubility and volume | tells the modeller which formulation inputs matter for *this* drug | PBBM | S |
| 9 | **Excipients by function:** sugar alcohols, surfactants, pH modifiers, polymers, with mg per dose; test-versus-reference differences flagged (thresholds SME-governed) | functional excipients change exposure; the rest is context | PBBM | M |
| 10 | **CDISC import** (SDTM PC, PP, EX, DM, AE; ADaM) | when a client sends standard datasets, no AI is needed: times, BLQ status and LLOQ are explicit | clinical PK | M |
| 11 | **Pre-flight check against EMA's rejection reasons:** autoinhibition, gut CYP3A, justified fm, relevant verification data, qualification set per pathway | catches the most common objections before submission | regulatory | M |
| 12 | **Two models agree on what code cannot check** (codes, arms, batches); disagreement is highlighted | agreeing answers were 94 % right, disagreeing ones 41–50 % | AI | S |
| 13 | **Revised delivery: a diff** of what changed (re-assayed samples, changed flags), with the reason recorded | clients resend | clinical PK | M |
| 14 | **The AI extraction's own credibility file**, following FDA's 7-step framework (2025 draft) | Part 11 and reviewers will ask how the AI was validated | AI | S |

**Two problems the regulatory review found in a locked ruleset** (`pbpk_acceptance_criteria.yaml`, not edited):
1. The title cited for `guest_2011` is not the paper's. PubMed has "Critique of the two-fold measure of prediction
   success for ratios…" (PMID 21036951).
2. The medium-risk 1.5-fold limit is attributed to the EMA guideline, but the review found no source for it.

Both are for the SME's review (D7).

---

## 9. Gap 2: "0.1 N HCl" as a pH (your choice)

The dissolution table names its medium "0.1 N HCl" and gives no pH. By convention 0.1 N HCl is the pH 1.2 medium, but
the file does not say so.

- **Option A (recommended): code recognises standard media and labels the pH "by convention".**
  - A short table: 0.1 N HCl → 1.2, simulated gastric fluid without enzyme → 1.2, FaSSIF → 6.5, FeSSIF → 5.0, and so on.
  - The value shows as "pH 1.2 (by convention for 0.1 N HCl, not stated)".
  - The modeller confirms it once per project.
  - The table is SME-governed: UNVERIFIED in `dataroom_rules.yaml`, with a version bump.
- **Option B: ask every time.** The medium stays without a pH until the modeller types one. Safer, slower, and the same
  question comes back for every delivery.

**Decision:** D4.

---

## 10. Order of work

Each phase ends with tests, the CHANGELOG, a merge to `main` and a short report to you.

| Phase | Content | Size |
|---|---|---|
| 0 | Done today (§1) | — |
| 1 | Direct Anthropic provider and presets (§3); pause and auto-resume (§4); answer cache and cache-friendly prompt order (§5.2–5.3); cost estimate before a paid run; the hard cap if approved (§2.4) | about 1 week of sessions |
| 2 | Requirement drafts from the literature (§6) → your or the SME's review → the Data room checklist wired to them; coverage ledger; context-only store; worded data requests with alternatives | about 2 weeks |
| 3 | Science checks: features 3–9 (§8) | about 2 weeks |
| 4 | The end-to-end walk to the MAP (§7), on free models, then a real delivery in-house; then the Claude calibration run and the demos | about 1 week |
| 5 | Later: CDISC import, revised-delivery diff, project memory, two-model agreement, pre-flight check | — |

---

## 11. Decisions needed from you

| # | Question | My recommendation |
|---|---|---|
| D1 | API key or identity federation? | **API key**, in its own Console workspace with a spend limit. |
| D2 | May I spend about $5 of the credit on **one** calibration run on a made-up delivery, which doubles as demo 1's rehearsal, once phases 1 and 4 are done? | **Yes**: without it, every cost figure above stays an estimate. |
| D3 | A hard per-run and monthly cap that **pauses** runs, for **paid** models only (free ones keep warn-only)? | **Yes.** |
| D4 | "0.1 N HCl": option A (standard media by convention, labelled, confirmed once) or option B (ask every time)? | **A.** |
| D5 | May I draft the per-application requirement tables from the literature, as UNVERIFIED drafts for the SME's review? | **Yes.** |
| D6 | Treat Anthropic like NVIDIA and Groq: a client's files go to it only with the client's written permission recorded on the project? | **Yes.** |
| D7 | Send the two ruleset findings (§8) to the SME? | **Yes.** |
| D8 | The phase order of §10? | As written; tell me if demos must come sooner. |

### Decided by the owner, 2026-11-24 (all eight approved; "go ahead with all phases")

| # | Decision |
|---|---|
| D1 | API key. The owner creates a Console workspace "Modeler One", creates the key inside it, sets a **$90 spend limit** on the workspace, and adds the key on the server through Admin → Keys. |
| D2 | One calibration run, about $5, on a **made-up delivery only**, after phases 1 and 4. Its **cost and accuracy are shown to the owner before any other Claude spend.** |
| D3 | A hard cap for **paid models only**: **$10 per run, $90 per month**. Reaching it **pauses** the run and never fails it. Free and in-house models stay warn-only. |
| D4 | Option A: standard media recognised by convention (0.1 N HCl → pH 1.2, …), labelled "by convention, not stated" and confirmed once per project. The table stays **UNVERIFIED**, with a version bump (`dataroom_rules.yaml` 0.1 → 0.2: SME-governed, not on the locked list). |
| D5 | Requirement lists drafted from the literature as **UNVERIFIED drafts**. They become templates only after the owner's review. **The locked templates are not changed.** |
| D6 | Anthropic is treated like NVIDIA and Groq: a client's files go to it only with the client's written permission recorded on the project. Made-up demo data needs none. |
| D7 | Both ruleset findings go in a short note the owner can forward; the locked file is not edited. |
| D8 | The phase order of §10 as written. |

---

## Appendix: the literature reviews

| Report (in `docs/research/`) | Records screened | Cited |
|---|---|---|
| `2026-11-24-regulatory-data-by-context-of-use.md`: what each application needs, acceptance criteria, credibility, reviewers' objections | ≈ 290 | ≈ 50 |
| `2026-11-24-pbbm-absorption-inputs.md`: which formulation and in-vitro inputs change predictions; Caco-2 calibration; PBBM pitfalls; regulators' data expectations | ≈ 360 | 126 |
| `2026-11-24-clinical-pk-data-curation.md`: BLQ, nominal versus actual times, NCA conventions, exclusions, statistics, verification criteria, CDISC | ≈ 215 | 72 + 9 guidances |
| `2026-11-24-ai-extraction-cost-reliability.md`: LLM extraction accuracy and error types, regulated use, cost and reliability engineering | ≈ 370 | ≈ 95 |

**Limits:**
- Abstracts were screened; key papers were read in full.
- fda.gov and ema.europa.eu could not be reached from this environment, so the wording of guidances is marked "recalled,
  verify" where it was not quoted from a paper.
- No numbers in this plan become rules without the SME's approval.
