# Page-by-page review of the web app (plan)

Status: **in progress** (2026-10-28). The method is agreed. The owner chose to start with Start (2026-10-24); its
marks and PR are in §4.

The owner sent 13 page exports (2026-10-23): "its so difficult to navigate and understand... we need to plan on
understanding each fields and data on each page and correct it and work on that one page at time". This document
proposes how to work through the pages, and records a first pass of what the exports show.

## 1. How we work through it
For each page, in turn:
1. **Map every element.** List each field, column, button and message. For each one, say what it is, where its value
   comes from (the code path), what uses it downstream, and whether a modeller needs it at that point. Values come
   from the code and are never guessed.
2. **The owner decides.** For each element: keep, change, move or drop, with a note. This uses an interactive review
   page like the P0–P5 map of 2026-10-17, which worked: my suggestion on each row, the owner's buttons, and the
   choices read back.
3. **One PR per page.** Each PR carries:
   - the agreed changes, with the API changes they need;
   - the updated e2e spec;
   - a before and after screenshot in light and dark;
   - a CHANGELOG entry.

   The next page starts once the owner has merged it.

**Order: the flow a modeller follows.** Run and the Review inbox go first, because they are where a running
campaign is followed and decided today:
1. **Run** (the project page) and the **campaign monitor**: the monitor was not in the exports, but it is where a
   campaign is watched.
2. **Review inbox.**
3. **Projects**, then **Start a project**, then **Start**.
4. **Inputs:** Compound, Formulations, Individuals, Simulation settings, Studies.
5. **Review & sign:** studies and roles (D1/D2/D3), the inputs, the estimation plan, the validation plan,
   applications, credibility, the validator.

**Reference project:** the owner's real project, or Dapagliflozin (T-56), whichever the owner prefers. Each page is
judged on real data, not on test fixtures.

## 2. First pass: what the exports show
These notes come from the PDFs only, read as text. They are inputs to step 1, not decisions.

| Page | What is hard to read or wrong |
|---|---|
| **Projects** | 17 rows, 8 of them named "Dapagliflozin PBPK", plus "test" and "Example-A". The table has no status, step, owner, created date or last activity. "Program risk" reads medium on every row. There is no way to archive a test project. "Open questions" is not explained. |
| **Start a project** | Clear on the whole. It does not say what happens to each kind of file, or that a published OSP model can be the starting point. |
| **Start** | The drug's PubChem CID, SMILES, InChIKey and molecular weight show "not set", while Inputs uses MW 408.87 from the OSP model. "How the model is used" and "What a wrong decision means" are not set, yet the tier shows "Saved: medium". The data checklist has 27 rows whose status ("—") is not linked to Inputs, which says everything is ready. |
| **Inputs · Compound** | Many rows have no name, so the raw id stands as the label and again below it (`elim.hepatic.Hepatic-CYP.clspec`, `phys.halogens.Cl`, `bind.partner`). Every row repeats "Open Systems Pharmacology — grade B · in the model · Sources (1)". There is no grouping by building block (physico-chemistry, binding, ADME), and nothing marks which values a stage may fit or which are measured. |
| **Inputs · Formulations** | The formulation parameters use raw ids. About 40 study rows repeat "ir tablet Dissolved", and the page does not explain that a tablet is modelled as dissolved. |
| **Inputs · Individuals** | 40 identical forms ("European ICRP 2002 male 30") across 4 pages. T2DM and renal-impairment studies get the same healthy 30-year-old man without a warning. The age, weight and height fields are empty. |
| **Inputs · Simulation settings** | 40 rows reading "PK-Sim's defaults". Raw ids such as `sim.Dapagliflozin|logP (veg.oil/water)`. |
| **Inputs · Studies** | One long table with long slug names. "model building · osp library" appears on every row. There is no preview of the observed profile, and the role is read-only here and set on another page. |
| **Review & sign** | 33 of about 40 studies go to S5 external validation, and the reason for each role is not shown. Each of the D1, D2 and D3 views lists all 40 studies. Legacy wording remains ("Run the campaign (P6)"). |
| **Run** | It says "No observed data yet" while a campaign runs at S4: the box reads `GET /projects/{id}/studies`, not the studies on Inputs. The "Questions of interest" table is empty. "Parameter framework" is a legacy link. |
| **Review inbox** | Test fixtures (`camp-101`, `doi:10.1000/example`) sit among real items. Items show no project name and no date. Escalations from abandoned campaigns stay forever. "Select an option…" does not explain the options. |

**Found in the first pass and worth fixing early, whatever the page decisions:**
- **Run** contradicts itself ("no observed data" during a campaign).
- **Start's identity** is not filled although the drug is known.
- The **inbox** mixes fixtures and stale items with real decisions.

## 3. Decisions for the owner
1. **The method:** an interactive review page per screen, then one PR per page. Is that agreed?
2. **The order:** Run and the inbox first, as proposed, or the flow order (Projects → Start → Inputs → Review →
   Run)?
3. **The reference project:** your real project or Dapagliflozin?
4. **Test projects and stale escalations on the server:** they are your data. Shall I add an archive (hide, never
   delete) so the lists show real work only?

## 4. Page 1: Start (marked 2026-10-25…28, built 2026-10-28)
The owner marked 48 elements on the review page `FLcNRsUrnCJcEcDTkDhqzE` (collection `decisions`): 12 keep, 11
change, 7 move, 17 drop, and a general note. The owner asked for pushback, not blind implementation ("think think
think").

### 4.1 Built (this PR)
- **Marked in place:**
  - What still needs the person is marked red on its own field, with a ⚠ line (`f.waiting`).
  - The steps after Start are locked until it is done.
  - There is no side panel.
- **Kept:**
  - the drug, CID and SMILES (the agent fills them);
  - the question of interest, context of use and BCS class;
  - influence, consequence, "Why this tier" and "Save the model risk";
  - the formulation types and the step bar.
- **Changed:**
  - **Applications** say what data each adds (`b2.apps`).
  - **Pathways** are one list, each with its kind; a pathway the published model has and the proposal does not name
    is flagged (`b2.kinds`, `b2.named`).
  - **Nonlinearity and EHC** are yes / no / not stated (`b2.nonlin`, `b2.ehc`).
  - **The tier** shows its criteria (`b3.tier`).
  - **What is modelled** reads as one product line (`b4.model`, `b4.site`).
  - **The dose** is edited on its route (`b4.routes`).
- **Moved:**
  - the internal target, under the tier (`b3.target`);
  - History, to the Projects page (`f.history`);
  - the agent notice, under "Read the proposal again" (`f.read`; the redesign stays with the owner);
  - the document viewer, to a dialog opened from a value's source (`f.viewer`, until the library is built);
  - MW, to Inputs, where it already shows as `phys.mw` with its source (`b1.mw`).
- **Dropped:**
  - the title, agent chip, hint, open-questions list and InChIKey;
  - "How the model is used" and "What a wrong decision means";
  - the data checklist (`b5.*`);
  - Proposal notes (`b6.*`).

  The brief keeps every dropped field, and the data plan is still derived from it on every change.

### 4.2 Not built here, planned
- **The project document library** (`b1.files`, `b1.add`, `f.viewer`): `docs/plans/2026-10-28-project-document-library.md`,
  three PRs. Until it lands, Start keeps its file list and "Add files", without the type selector.
- **Product types the builder does not make yet** (`b4.modality`). Each is refused at Start today with "not supported
  yet"; each is added one at a time, with the SME, and each needs its own plan:

  | Product type | What it needs before the builder can make it |
  |---|---|
  | **Large molecule** (therapeutic protein, antibody) | PK-Sim's protein model: FcRn binding, target-mediated disposition, endosomal clearance. New requirement templates, rulesets and reference models. |
  | **Other modality** (oligonucleotide, cell or gene therapy, ADC) | Is a PBPK model the right tool for each? An SME call first; some may stay out of scope. |
  | **Minimal PBPK** | A reduced model structure (MoBi, not a PK-Sim snapshot). It needs its own builder path and reference runs. |
  | **Local site of action** (lung, skin, eye, gut lumen) | A site model: an inhaled, dermal or ocular deposition model, or a tissue sub-compartment. Its own data and acceptance criteria. |

- **Inputs is not hard-blocked** before Start is done. It shows a red banner instead, because 13 browser specs open it
  directly. A hard block needs those specs to finish Start first. Proposed as a follow-up once the owner agrees.
- **Delete on the Projects page** (`f.history`): not built. A project is a Part 11 record, so archive (hide, never erase)
  is proposed instead. This waits on the owner's answer.

### 4.3 Questions for the owner (from the general note)
These are in the PR description and the reply of 2026-10-28:
- the M15 texts (influence and consequence rationale);
- an early list of what only the client can send;
- products, populations and scenarios;
- Delete or Archive;
- the Inputs hard block.
