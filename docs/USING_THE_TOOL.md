# Using Modeler One — get it running, open the examples, build a PBPK model

Every simulation the tool runs on the server is **real PK-Sim** (ospsuite 12.4.4 / PK-Sim 12.3.173 through
`services/engine-worker/r/run_job.R`). The stand-in engines in `deploy/dev/` are test fixtures only; a campaign run
on one is labelled "Not a PBPK result" on every page, so it can never be mistaken for evidence.

## 1. Start the tool on the server (from the Mac)

```bash
cd ~/Modeler_One_AI            # the git checkout on the Mac
git pull origin main
bash deploy/dev/deploy_to_server.sh      # rsync, install, build the web app, restart API + web, print the URL
```

Open `http://<server>:3000` (the LAN address the script prints, or the tailnet address after
`bash ~/Modeler_One_AI/deploy/server/setup_tailscale.sh` on the server, which gives a stable address from anywhere).

## 2. Load every worked example (on the server)

```bash
ssh adt-server 'bash ~/Modeler_One_AI/deploy/server/seed_examples.sh'     # 3 campaigns at a time
ssh adt-server 'tail -f ~/modeler-logs/seed.log'                           # progress
```

It creates one project per example through the API, exactly as you would in the browser (project, CPF, studies,
analysis plan generated and signed, campaign started), and runs the campaigns on PK-Sim a few at a time. Run it again
at any time: examples already in the tool are skipped. It refuses to start with less than 5 GB free.

| Project | What it shows |
|---|---|
| Dapagliflozin (as published) / (refit S1-S3) | The plan-exit drug: 40 real studies (IV microdose, solution, tablets, fed, multiple dose, renal impairment). As published: the peer-reviewed parameters judged stage by stage. Refit: the parameters MS-01 lets S1–S3 fit, freed and fitted on PK-Sim. |
| Rifampicin (as published) / (refit S1-S3) | The second plan-exit drug: saturable AADAC metabolism, OATP1B1 / P-gp transport, auto-induction, 53 studies. |
| Midazolam, Alfentanil, Alprazolam, Clarithromycin, Digoxin, Metformin, Raltegravir, Ketoconazole, Voriconazole, Itraconazole | The other published OSP library models with their clinical data (CYP3A4 / UGT metabolism, transporters, particle dissolution, loading-dose regimens, pH-dependent solubility, fed-state alternatives). |
| Verapamil, Omeprazole, Dabigatran, Itraconazole, Ketoconazole systems | Parent with enantiomers and metabolites simulated together (sum observers, CYP2C19 poor metabolisers, prodrug). The parent is fitted and gated; metabolite data are reported (phase 2 needs the MS-01 amendment). |
| Aciclovir (illustrative) | A hand-made quick check of the software path; labelled as such, not evidence. |

## 3. What each campaign does

S0 readiness → S1 IV → S2 oral fasted → S3 formulation / fed → S4 internal validation → S5 external validation → S6
prediction (sensitivity, prediction intervals; **stops for your signature**) → S7 report and package.

- **Escalations** wait for you in **Your work**, and as a bar saying **A decision is waiting** on the campaign's page
  and its project's pages, for the people who may decide. A stage escalates when the model misses the acceptance criteria
  (1.5-fold at medium risk) on a study it must fit, and no permitted action fixes it. Open it to decide (accept with a
  justification, exclude data, change what is fitted, stop); every decision is signed and recorded. Published models
  do escalate on some studies: the pipeline judges them by the same rules as a new model.
- **S7 package** (`package.zip`, only when the re-run of every bundled simulation reproduces the results at 1e-6):
  the final CPF, the signed analysis plan, the observed data, the S4/S5 simulations as PK-Sim snapshots **and as
  PK-Sim projects (`pksim/*.pksim5`, open them in PK-Sim)**, their results, every fit's specification and result, S6,
  the report (MAR) as PDF/A, Word and Markdown, a manifest with hashes, and `rerun_all.R`.

## 4. Your own compound

**Finding your way.** The bar at the top holds **Your work** (everything waiting on you, with its count), **All
projects**, **Help** and whether the API answers. The navigation on the left lists **Home**, **Your work**,
**Projects**, **Campaigns** and **Start from proposal**; with a project open, its **Overview**, its four steps (each
with its state), **Data plan**, then its records (**Compounds**, **Documents**, **History**, **Agent activity**), its
**Members** and **Settings**, and **Add data**. The platform's owner also sees the **Admin console**. A page's
breadcrumbs say where it is; a page's tabs keep their choice in its address, so a link opens on the same tab.

Every project starts from its proposal: **Start from proposal** (in the navigation on the left), then four steps:
**Start**, **Inputs**, **Review & sign** and **Run**. The Quick start wizard is gone (R5): to begin from a published OSP
model, start the project for that drug and, on Inputs, **Take the published OSP model's values** (§7). The tool
generates the analysis plan from your studies (the MS-01 data split), you sign it, and the campaign runs S0 → S7 on
PK-Sim.

**The Projects page** lists your projects. Each project's **History** holds its records in four tabs: the **Audit
trail** (every change, its members, archiving), the **Signatures** given on its records (escalation decisions
included), every artifact's **Versions**, and what is **Out of date**. **Agent activity** lists every agent run on the
project, and each run's steps. A project is never deleted: it is a Part 11 record. **Archive** hides a test or finished
project from the list, with a reason, and keeps everything it holds; it still opens by its address. **Show archived**
lists them, and **Restore** brings one back, with a reason. A project whose campaign is still running is not archived.

**Documents** (in the navigation, under the open project's records) lists every document
of the project: the proposal, its annexes, the client's files, retrieved records. For each it shows who added it (a
person, an agent or the system), its role, format and pages, its versions, and what the project took from it. Those
contributions are the values, datasets and brief fields that cite the document, each linked to where it is used; a
document nothing cites says so. Search, filter by role, by who added it or by status, sort, and open a document on its
pages.

**Add data** (in the navigation, at the end of the open project's pages) adds files at any step: PDF, Word, Excel, CSV, JSON, Markdown or
text. Say what they relate to: a step (the open page's step is preselected) and, if you like, a task such as
"Formulations". Workbooks go to the client's data on Inputs and everything else to the documents as an annex; switch
either per file. A document is never deleted: **Withdraw** it on Documents, with a reason. It stays listed, marked
withdrawn, and the agents no longer use it. Nothing new is taken from it (a value, a digitized figure, a client sheet)
until it is **Restored**. Values already taken from it keep their source; reject them on Inputs if they must go.

The literature agents read the library before they search outside, and they do not fetch a paper the library already
holds. They store a paper's full text only when it is open access; any other paper is kept as its abstract, and the agent
asks you for it (Inputs lists the request). Under **Added**, each paper an agent stored names where it came from, with
its link, and says whether the full text or only the abstract is held.

**From a proposal (Step 1 · Start):** **+ Start from proposal** → name the drug and drop everything in one go: the
proposal, its annexes and what the client sent (many files or one zip). Tick **Proposal** on the technical proposal (a
file named like one is ticked already); nothing else is tagged. The client's files go to the project's **Data room**, its
run starts at once, and you land on it to watch the files read. With no client files you land on Start → the Start
screen fills the drug's identity from PubChem and, with an agent configured, the brief from the documents.
Each value shows its source; click it to see the page it was read from. Anything that still needs you is marked red on
its own box, with a ⚠ line saying why, and the bar at the bottom counts what is left. The steps after Start stay
locked until nothing is: Inputs, opened by its address, says what Start still needs and links back. A project that has
already gathered its inputs (or signed its plan) keeps its later steps open, with a red banner on Inputs, if Start
later needs something again.
- **The question:** set what the documents do not say and correct what is wrong; no "why" is asked. Each application
  says what data it adds.
- **The drug's disposition:**
  - The pathways are one list, each enzyme, transporter or route with its kind. A pathway the published OSP model has
    and the proposal does not name is flagged, with **Add it**.
  - Nonlinearity and enterohepatic recycling are yes / no / not stated. "No" to nonlinearity means linear PK, so Km and
    Vmax are not asked for.
- **Model risk (ICH M15):** rate model influence and decision consequence, then save the tier they admit. With an agent
  configured, it suggests ratings too, but nothing is preselected: its suggestion shows only once you have saved your
  own. A rating that matches is noted. A rating that differs is flagged, and Start waits until it settles on one:
  **Take** the suggestion (then save the model risk), or **Keep** yours and say why. A later rating or a new suggestion
  asks again, and Review & sign shows the signer a rating kept against the suggestion, with the reason. The signed MAP
  carries the whole assessment (the ratings, why each, why the tier, any rating kept), and the report's ICH M15 table
  shows it. The tier's acceptance
  criteria show beside it. Under the ratings, say why each is what it is: **How the model is used** and **What a wrong
  decision means**. With an agent, it drafts both from the question and context of use; **Confirm** or **Change** each.
  Start is not done until both are in your words or confirmed by you, and Review & sign shows them to the signer. An
  optional internal target sits under them and is never looser than the tier.
- **What is modelled:** modality, PBPK model and site of action read as one line once all three are supported. Then
  come the formulation types, and the routes with their doses. What the builder cannot model yet is refused there.
- **What to request from the client:** only what the client alone holds (test-product data, BE studies, dissolution,
  biorelevant solubility…), from the data plan, each with what it serves. It follows the applications and the proposal as
  they change. **Download the request (.xlsx)** gives the client-data workbook with these items on a first sheet, saying
  where each goes; the client fills it and sends it back, and it is read cell by cell on Inputs. The agents find the
  rest in the documents and the literature.

The proposal's products are on Inputs → **Formulations**, and its populations on **Individuals**, where they are used:
each with its source, changed, added or removed (with a reason) in place.

Nothing on Start is approved: you review everything once, when you sign the plan.

## 5. Checks against the published models

`bash deploy/reference/run_all.sh roundtrip -j 8` on the server (or the GitHub Actions workflow "Reference models
(PK-Sim)", which runs on every push) rebuilds every published simulation from the imported CPF and compares both on
PK-Sim: identical inputs must give identical curves (1e-6 of the peak). Results: `reports/reference/<stamp>/summary.md`.

## 6. The client's spreadsheets (on Inputs → Studies)

Add the client's files when you start the project (one upload with the proposal), with **Add data** in the navigation,
or on the Inputs step's **Studies** tab (**Add the client's files**). Workbooks are split into sheets; PDF, Word and Markdown
are kept as citable documents. The client-data template (**client-data template** on the same tab) is read
automatically, cell by cell. The data plan, derived from the brief, ticks off what arrives. Nothing is approved.

1. **Read each data sheet** ("Read this sheet"). The sheet appears next to a form filled in from what the sheet
   states: header row, data rows (Mean / SD rows under the subjects are left out), times down a column or across the
   top, subject / period / value columns, units, LLOQ and dose quoted from their cells. "Found in the sheet" says what
   was taken from the file name instead (study id, food state) and what is missing.
   - Fill what the sheet does not say: number of subjects, formulation, the study's purpose (BE, fed and
     other-formulation studies: **external validation**), the infusion time for IV data.
   - Give each BE arm its own study id (e.g. `230-23-TEST`, `230-23-REF`).
   - Dissolution: name the product exactly as the brief does and its role (TEST / RLD); the release-model item and the
     f2 comparison count only such profiles. The profiles, their Weibull fit and f2 are on the **Formulations** tab.
   - "Check what will be read" shows the subjects, times, the first values with their cells, and every problem in
     words (e.g. a cell that says `NS`: add it under "cells that mean no sample"). "Save these data" keeps it.
   - "Same layout as the last sheet" copies columns, units, LLOQ and cell texts to the next file; the rows and the
     study (id, dose, route, formulation, food, subjects, purpose) stay this sheet's own.
   - Read a sheet again to correct it: the new reading replaces the earlier one (its datasets are left out).
   - With agents on, **Read the data sheets (agent)** lets the reading agent read the file's data sheets first. Code
     checks every reading it proposes: each quote is in its cell and states its value, a unit, LLOQ, dose or n stands on
     a quote (never guessed), and the reading applies without a problem. A sheet with a proposal shows **reading
     proposed** and opens on the agent's reading, marked as the agent's, with its notes. Check it against the sheet,
     correct anything wrong and save: nothing is read in until you save.
2. What the client sent that the checklist did not promise is listed under **Delivered, not in the data checklist**.

## 6a. The Data room: drop the client's delivery, get the evidence and the PK-Sim inputs

New projects use the Data room as their Inputs step (existing projects keep their Inputs page).

1. **Drop the delivery.** Drag the zip, or many files, onto the Data room, then press **Run**. The progress panel
   shows each stage: reading (scans go through our own OCR on the server), understanding the question, sorting the
   files, extracting, checking every number, putting it together. You can leave and come back.
2. **Confirm the question card.** It holds what must be answered, for whom, the products compared and the checklist of
   inputs. Add or remove items, then confirm.
3. **Read the sections.** Every value shows its source chip; click one to see the page with the line highlighted.
   Statuses: Verified (two sources agree, or our recomputation reproduces the client's number), Sponsor data,
   Literature, Calculated, Entered, Conflict, Missing.
4. **Decide.** Each decision card has a suggestion and the reason: the analysis set, the population database, the meal
   template, the reference solubility, the release profile per product. Choose, and add a reason when you change
   the suggestion.
5. **Send the data requests.** They are grouped A (formulation and manufacturing), B (in vitro), C (drug substance and
   disposition) and D (clinical). Edit the wording, mark a request not needed, and export it.
6. **Send to the model.** It is enabled when nothing blocks it, and it says what blocks it in plain words. It signs and
   publishes the inputs into the stores Review & sign and Run already use.
7. **Export the report.** It opens the evidence report as a printable page; save it as PDF.

**Choosing the models.** Admin → Models lists the Data room's five agents, A6 to A10.
- **By default they run on the in-house Qwen Coder** (the server's LiteLLM proxy). An agent nobody clicked follows the
  server's environment. It is free, and client files never leave the server.
- **One check on the server:** Ollama should give Qwen a context window of at least 32,000 tokens. Ollama's default
  is much smaller (about 4,000), and it then cuts the agents' prompts without saying so. Every agent now notices a cut
  prompt and first asks Ollama for a 32k window itself (LiteLLM passes the request's `num_ctx` on to Ollama). If the
  server cannot give it, the agent shortens its earlier turns and leaves the oldest out (the instructions, the task
  and the latest turn are kept; what its tool calls recorded is kept too) and asks again. So "Read the proposal" on Start still finishes on a small window, but it
  reads less at a time and takes longer. A request that cannot fit even then (a Data room file's pages) fails and says
  what to change. To set the window, start Ollama with `OLLAMA_CONTEXT_LENGTH=32768`, or create a model with
  `PARAMETER num_ctx 32768` and point the proxy's `qwen-coder` alias at it.
- **Four buttons per agent:** Qwen Coder, Claude, gpt-oss-120b (GroqCloud) and Nemotron Ultra (NVIDIA's API
  catalog). GroqCloud's free tier allows 8,000 tokens a minute and per request, and 200,000 a day: too little for a
  whole delivery. For NVIDIA, create a key at build.nvidia.com (trial credits) and add it under Admin → Keys → "NVIDIA
  API catalog"; the address is fixed. Check its trial terms before you send it client files.
- **When a model cannot answer** (Admin → Models → "When a model cannot answer"): list, in order, the models every
  agent goes on with. When an agent's model gives no answer in time, has spent its daily limit, or its service is
  down, refuses the key or does not serve the model, the agent starts that task again on the next model in the list.
  A failure that will repeat rests the model for the next tasks too: 10 minutes after a timeout, 6 hours after a
  spent daily limit. A one-off server error on one document rests nothing. Each switch is said on the run's stage and
  kept in the agents' record. The list is empty until you fill it.
  - **Data terms decide what may be listed.** A cloud model in the list receives the client's files the agent is
    reading; each choice shows its service's terms:
    - Qwen Coder runs on your server.
    - GroqCloud says it does not train on inputs, and offers Zero Data Retention. Turn it on in the GroqCloud console
      before you list it for client work.
    - NVIDIA's trial terms let NVIDIA use inputs to improve its products. List NVIDIA only for made-up data, or for a
      client who has agreed.
  - **A sensible list for client work today:** gpt-oss-120b (GroqCloud, Zero Data Retention on) behind the in-house
    Qwen Coder. For tests on made-up data, add Nemotron Ultra.
  - **Each company has one setting for where its files may go, kept by the administrator.** A company is in-house only
    until the administrator records, on Admin → Companies → the company ("Where its files may go" → Change), the
    client's written permission for a cloud service: its reference (a letter, an email, a contract clause), an end date
    if it has one, and why. It applies to every person and project of that company at once; the company's people do not
    see it. A change asks you to confirm your identity and is audited on the company's trail.
    - Until then, a cloud model in an agent's setting or in the list is left out for that company's files.
    - With no model left, the agent stops and says an administrator must record the permission. Set the agent to Qwen
      Coder, or record the permission.
    - Permissions recorded on a single project before 2026-11-24 are no longer used: record them again for the company.
  - **The evidence report says how it was made:** which model and service wrote each answer, and any switch. A9 checks
    each extraction on another model than the one that wrote it, when the list has one; otherwise its note says it is
    not a second opinion.
  - The in-house model now streams its answer. A slow model that is still writing is no longer cut off at
    `MODELER_LLM_TIMEOUT_S`, which now counts between pieces of the answer (three times it in all). If your proxy
    cannot stream with tools, set `MODELER_LLM_STREAM=0`.
  - A timeout is tried twice at most, not five times. During a long wait on the server, `ollama ps` shows whether an
    earlier request is still running: Ollama serves one request at a time.
- **Any other OpenAI-compatible service**, such as a provider's free tier: Admin → Keys → "Another OpenAI-compatible
  service", with its address (ending in `/v1`) and key. Then on the agent's row choose More…, that provider, and type
  the model name. Check the service's terms before you send it client files: many free tiers log or train on what
  they receive.

**What the AI may and may not do.** It says where a table is and what its columns mean, and quotes facts. Code reads
every number from the cells and checks every quote against the file. A quote that is not in the file, or a value that
is not in its quote, is refused and never reaches the room.

## 6b. AI model keys, end to end (the server, GroqCloud, NVIDIA, the Claude API)

The agents run on the in-house model by default, which needs no cloud key. A cloud model needs a key from its
service. The key is stored sealed on the server, chosen per agent, and allowed per project. Never paste a key into
a chat, an email, a document or the repository. If one ever was, make a new one and retire the old one.

**Step 1. The server's master key (once).** It seals every key the console stores.
1. On the server, open `~/.modeler-secrets.env` (copied from `deploy/server/modeler-secrets.env.example`, mode 600).
2. If `MODELER_MASTER_KEY=` is empty, make one: `python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())'`.
   Put it after the `=`.
3. Restart the stack: `bash deploy/server/stop_modeler.sh`, then `bash deploy/server/run_modeler.sh`.
4. Keep a copy of this line somewhere safe, outside the server. Changing or losing it makes every stored key
   unreadable: they must then be added again.

**Step 2. The in-house model's key (the LiteLLM proxy on the server).** This is the key the agents use for Qwen
Coder. It is LiteLLM's own master key, set when LiteLLM was started on the server:
1. Find how LiteLLM runs: `ps -ef | grep -i litellm`. The command shows its config file (`--config ...yaml`), if any.
2. The key is either `general_settings: master_key:` in that config file, or the `LITELLM_MASTER_KEY` variable of
   the process that started it. It usually starts with `sk-`.
3. Put it in `~/.modeler-secrets.env` as `LITELLM_KEY=` (with `LITELLM_BASE=http://127.0.0.1:4000/v1` and
   `MODELER_LLM_MODEL=qwen-coder`), or in the console: Admin → Keys → Add a key → "In-house model (LiteLLM proxy)",
   with the proxy address and the key.
4. Check it: `source ~/.modeler-secrets.env && uv run python -m modeler_agents.llm_check`.

**Step 3. Get a cloud key** (only for the services you will use):
- **GroqCloud** (gpt-oss-120b): sign in at console.groq.com, open API Keys, create a key and copy it. It is shown
  once and starts with `gsk_`. Before any client file goes there, turn on Zero Data Retention for your organization
  in the console's data settings. The free tier allows about 8,000 tokens a minute: enough for a check, too little
  for a whole delivery.
- **NVIDIA API catalog** (Nemotron Ultra): sign in at build.nvidia.com, open a model's page (for example Nemotron),
  choose "Get API Key" and copy it. It starts with `nvapi-`. The trial's terms let NVIDIA use what it is sent:
  made-up data only, unless the client has agreed in writing.
- **The Claude API** (Claude Opus 5.5 and Sonnet 5.5, with Anthropic's own Console key; decisions D1 and D3 of
  `docs/plans/2026-11-24-data-story-next-phase.md`):
  1. Sign in to the Claude Console. Create a **workspace** named "Modeler One".
  2. In that workspace's limits, set a **spend limit of $90**. The Console then stops requests before the credit
     runs out, whatever the platform does.
  3. Inside that workspace, create an API key named for the server (e.g. "modeler-server"). Copy it: it is shown
     once and starts with `sk-ant-`. If the Console asks "identity federation or an API key", choose **Continue with an
     API key** (our server has no cloud identity for federation).
  4. Store it in step 4 below as **"Claude API (Anthropic Console)"**. Its **Test** lists the models the key may use:
     no message is sent and nothing is spent.
  5. It is a paid service: the platform pauses a run at **$10** and stops paid use for the month at **$90** (Admin →
     Limits), and a client's files go to it only with the client's written permission (step 6).
  6. **The calibration run (D2, about $5, once):** after the key is active (step 4), on the server:
     `bash deploy/server/calibrate_dataroom.sh --dry` shows the models, the estimate and this month's spend, with no
     call. Then `bash deploy/server/calibrate_dataroom.sh` runs every Data room agent once on the made-up Exampleamide
     delivery (the "Claude demo" preset, hard-capped at $5.50; no client file, no project touched). It ends with a
     **COST** line (by agent) and an **ACCURACY** line (how many of the delivery's 60 values it got right; Nemotron
     Ultra, free, 2026-11-24: 58). Send those lines to the team before any other Claude spend. Leave the agents on their
     current models until then.

**Step 4. Store the key on the server, from the console** (no restart, no file):
1. Admin → Keys → Add a key. Choose the service, paste the key and give a reason. Confirm your identity when asked.
   The page then shows only the key's last 4 characters; the key itself is never shown again.
2. Press **Test**. It asks the service for the models it serves with this key (no cost) and records the answer.
3. Press **Make active**. The service's earlier key, if any, is retired.
4. A key older than 90 days is marked for rotation: add a new one, test it, make it active.

**Step 5. Choose the models.** Admin → Models:
- **Presets**, one click for every agent, each with its estimated cost for a ten-file delivery: Free (NVIDIA and
  GroqCloud), In-house only, Claude demo (Opus 5.5 extracts, Sonnet 5.5 for the rest), Claude all Opus. A preset whose
  service has no active key says so and changes nothing;
- one click per agent: Qwen Coder (in-house), Claude (on Bedrock), Claude Opus 5.5 or Sonnet 5.5 (the Claude API),
  gpt-oss-120b (GroqCloud), Nemotron Ultra (NVIDIA);
- "When a model cannot answer": the models every agent goes on with, in order (§6a).

**Step 6. Allow it for the company.** A company's client files go to no cloud service until the administrator records
the client's written permission: Admin → Companies → the company → "Where its files may go" → Change → tick the
service, name the client's document (a letter, an email, a contract clause), add an end date if there is one, and a
reason. It applies to all the company's projects at once. Until then the agents use the in-house model only for that
company's files, and stop and say so if they have none. The Claude API counts as a cloud service here, like GroqCloud
and NVIDIA. For a company that holds only **made-up demo data** there is no client: tick the service and write
"made-up demo data, no client" as the document, so the record says why.

**Step 7. Check it works.** Admin → System status shows each service's active key, its last test and whether the
agents have a model. On a project, the Data room's run says which model wrote each answer, and the evidence report's
"How this report was made" lists them.

**Without the console** (one model for every agent, from the secrets file): set `MODELER_LLM_PROVIDER=groq` with
`GROQ_API_KEY=`, `MODELER_LLM_PROVIDER=nvidia` with `NVIDIA_API_KEY=`, or `MODELER_LLM_PROVIDER=anthropic` with
`ANTHROPIC_API_KEY=` and `MODELER_LLM_MODEL=claude-sonnet-5-5`, then restart. The console's per-agent
choices, when made, take precedence over the file.

## 6c. People and companies (the admin console)

Everything is done in Modeler One's admin console; Keycloak's own console is needed only to give the platform-admin
role (`modeler-admin`), which stays there on purpose.

**Once, from the Mac:** connect the console to Keycloak. It runs on the server (`ssh -t` gives it a terminal for the
password prompt); run on the Mac itself, it stops and says so.
```bash
ssh -t adt-server 'bash ~/Modeler_One_AI/deploy/server/keycloak.sh connect'
```
Keycloak asks for its administrator's password in the terminal (it never reaches the app). The command sets up the
console's service account, makes it a new secret and stores it as the console's active key. Run it again any time to
rotate that secret.

**Add a person:** Admin → Companies → the company → *Add a person to this company* (or Admin → People): username,
email, name, roles, and why. Confirm with your password and authenticator code.
- With a mail server in Keycloak, they get an email link to set their password and authenticator.
- Without one, the page shows a **temporary password once**. Copy it and give it to them in person or by phone. It
  is kept nowhere: if you leave the page first, use *New password* on the person to make another. At their first
  sign-in they choose their own password and set up their authenticator app.

**The authenticator (for now off for everyone but administrators).** Until the owner's end-to-end test, only
platform administrators give the 6-digit code; everyone else signs in and signs with their password alone, and new
people are not asked to set up the app. Turn it back on for everyone from the Mac:
```bash
ssh -t adt-server 'bash ~/Modeler_One_AI/deploy/server/keycloak.sh authenticator on'
```
(`authenticator off` turns it off again.) The People page says which holds.

**Change a person:** on the company's page or Admin → People → *Change*: roles, move to another company, disable or
enable, *Reset authenticator* (a lost phone), *New password* (a forgotten one). Each change needs a reason and is on the
company's audit trail. People are disabled, never deleted.

## 7. Inputs (step 2): from every source to a ready CPF

The Inputs page (`/projects/{id}/inputs`) is one workspace in PK-Sim's building blocks: **Compound**, **Formulations**,
**Individuals**, **Simulation settings** and **Studies**. Values flow in from the client's files, the literature agent,
PubChem and the published OSP model with no per-item acceptance (D-27). **Take the published OSP model's values**
(shown when the platform carries a published model of the drug) proposes every parameter of that model, citing it, and
the clinical datasets it carries, citing their publications; they rank below the client's and the literature's values,
and taking it twice adds nothing. The inputs are put together again after
every change. The side list **Still missing to run** names each open item; clicking one opens it on its tab. Nothing
is approved here: the one review is at the MAP signature.

- **One value per input (source selection 0.1, provisional until the SME signs).** Sources within 10 % of each other
  are one value with all of them listed ("+N agree"). Within 2-fold, the best source is kept (the client, then the
  literature by grade, then databases, then the published model) and the others are listed under the row for the
  review. Beyond 2-fold, **keep one** with a reason. Values are never averaged.
- **Exclude a source** from a row's sources, with a reason; the next best source takes over.
- **Add a value** in any row: the value, its unit, the source (DOI or URL) and the sentence that states it.
- **Held until you check it:** a value filed where a mistake is likely (a % bound as fu, fe as the GFR fraction), one
  with no conversion to the PK-Sim unit, or one moved to another parameter by a correction. Accept or reject it:
  it is the one value a person accepts, because a likely mistake must not reach the model unseen.
- **Filed under the wrong parameter.** `elim` (the data plan's "an elimination pathway"), a template such as
  `elim.hepatic.{enzyme}.km/vmax`, or a name the model does not use never reaches PK-Sim. Choose the real parameter
  (and the enzyme) and **Correct**, or **Reject**. The fraction excreted unchanged in urine goes under
  `elim.fe_urine`; PK-Sim's GFR fraction is a multiplier on filtration, not fe.
- **pKa: acidic or basic?** Choose and save. Two acidic (or two basic) values from different sources wait on you.
- **Individuals.** Each study's individual: the PK-Sim population database, sex and age (with the age range, weight and
  height when reported), or **Use the healthy adult default**, which the MAP lists as a limitation. It is never
  applied silently.
- **Studies.** Each study's facts, the role the MS-01 split proposes (changed only on Review & sign), whether it is
  blinded, a multiple-dose study's number of doses and interval, and **Leave out** with a reason. The client's sheets
  are listed on the tab itself: open a sheet, check the reading agent's (or code's) reading, and save. Add data also by
  filling the client-data template, digitizing a published figure, or typing a table in.
  - **Every dataset** lists each dataset however it arrived, with its values, its source and whether it is used; a
    blinded one is revealed for a check with the reason; **Leave it out** with a reason, or use it again. A digitized
    figure is used once you confirm **The overlay matches the figure**. **Find observed data (agent)** asks the
    observed-data agent.
  - **Digitizing a figure in a PDF:** **Digitize a figure** under Every dataset. A PDF's figures (images placed on
    its pages) are listed: pick one and the page is cropped to it. A figure drawn as lines is cropped by hand
    (**Crop to a region**, then two corners). **Zoom** enlarges the view. Calibrate the axes and pick the points in
    that view; changing the crop, the page or the zoom starts the calibration again. The dataset keeps the crop.
- **Formulations and Simulation settings.** The formulation of each solid study, the dissolution profiles with their
  Weibull fit ("Propose as release model") and f2, the calculation methods, the values set on the simulation, and each
  study's solver settings.

When the list is empty, **Go to Review & sign**.

## 8. Review & sign (step 3): the one review, then the signature

The Review & sign page (`/projects/{id}/plan`) is where everything is reviewed once, before the run (D-27).

- **Studies and roles.** The MS-01 canvas: drag a dataset onto a stage of the development and validation graph, with
  a reason; D1 and D2 free a parameter for fitting within bounds. Below it, each study's role, whether it is blinded
  until the signature, its demographics, and **Leave out** with a reason.
- **The inputs.** Every value the model takes, with the source the CPF keeps, its quote, grade and flags, who supplied
  it, and how many other sources agree. Filter it (flagged, changed by a person, from an agent, waiting on you).
  **Exclude** a value with a reason: the next source takes its place, and the plan asks to be brought up to date. The
  confidence shown sums up the grade, the flags and the agreement; it decides nothing.
- **The estimation plan.** Every numeric parameter, fixed or estimated: its start value and source, the stages MS-01
  lets it be fitted at, and its bounds. **Estimate** opens a form filled with the bounds MS-01 §2.2 proposes (relative
  bounds around the start value, absolute ones in MS-01's unit, kept within the physical bounds; 0.1–10× where MS-01
  gives none); choose the stages and give a reason. MS-01 keeps a measured fu fixed. Bounds wider than MS-01's
  default are said and must be acknowledged; bounds beyond the physical range, or a lower bound not below the upper,
  are refused. The rule is provisional until the SME signs it.
  An MS-01 candidate you do not estimate shows **the diagnosis may fit it in S1** (or its stages) with MS-01's own
  default bounds: when a round's diagnosis names it, the campaign may fit it within them (D-37). **Keep fixed** stops
  that, with a reason; **Let the diagnosis fit it** undoes it. The MAP lists every such candidate in its limitations.
- **The validation plan.** What S4 (internal) and S5 (external) judge under this MAP, which studies (a blinded one
  marked), and what happens when validation fails: S4 escalates and is never refitted; at S5 you choose an MS-01 §6.6
  path, signed as a deviation.
- **Applications.** The virtual bioequivalence design, when the brief names APP-14 (or APP-11, with "Add the VBE
  application"):
  - the TEST and reference formulations;
  - the intra-subject variability: a PK-Sim parameter path, its CV and its source. The engine checks the path before
    the trials run;
  - subjects × trials, the seed and the probability-of-success threshold;
  - the limits;
  - an optional observed BE study. Without it the result is "not validated".

  Nothing is defaulted, and what is missing is listed. Below it, each application of the brief says what the campaign
  does with it: runs at S6, the campaign itself, partly supported, or not supported yet. Acknowledge one it cannot run
  with a reason, and the MAP names it as a limitation. The brief's prediction scenarios are shown as not simulated yet.
- **Credibility (ICH M15).** The model risk, as set at Start or changed here with a reason; the **acceptance
  criteria** of that tier (the limits every round is judged by, provisional until the SME signs the ruleset) and an
  optional **internal target**, stricter than the tier only (the validator refuses a looser one). The signed MAP
  records it, and every round judges the internal studies' AUC and Cmax by it on top of the tier's limit (S5's
  external studies by the tier alone; MS-01 §8). The campaign's page and the report name it. The campaign's time budget and MS-01's fixed share of it
  for each stage, as the MAP signs them (more time means a larger budget, signed again); and the limitations the MAP
  will name, the brief's stated assumptions among them.
- **The live validator** lists what is still open; acknowledge a warning with a reason and it becomes a limitation.
  **Approve and Sign** generates the MAP from the plan and signs it (MIDD lead, step-up). After the signature a change
  is a deviation, signed into a new MAP version before it applies.

## 9. When something looks wrong: the project doctor

On the server, in `~/Modeler_One_AI`:

    source deploy/server/_env.sh
    uv run python -m modeler_api.doctor --list            # tenant, project id, drug, phases
    uv run python -m modeler_api.doctor <project_id>      # also saved as ~/modeler-logs/doctor-<project_id>.md

The report gives each phase's state and blockers, the evidence per parameter (conflicts, unknown names), datasets
(metadata only, never concentrations), readiness and its to-do list, the last audit events and recent API errors.
Paste it into a Claude session to get the project diagnosed. To let Claude look at the server directly, run a Claude
Code session on the server itself (`claude remote-control` in `~/Modeler_One_AI`); that folder is a deploy copy, so code
changes are still made in the git checkout and deployed.
