# Multi-compound models: parent, metabolites, enantiomers — design (2026-09-24)

Status: **proposed**, for the owner's review before implementation. Extends the S0–S7 plan
(`2026-09-24-s0-s7-real-pbpk.md`); nothing in the SME-governed content changes in phase 1.

## 1. Why

Five of the 25 OSP library models cannot be reproduced with one compound, and one more is only approximated:

| Model | Structure in the published snapshot | What the data measure |
|---|---|---|
| Verapamil | R- and S-verapamil each dosed (two protocols, 55.545 mg each for 120 mg HCl); each forms its norverapamil (`MetaboliteName`); all four inhibit CYP3A4 (MBI) and P-gp | racemic sum (46 datasets, `Sum-Verapamil` observer), enantiomers (17), norverapamil (19) |
| Omeprazole | esomeprazole + R-omeprazole dosed together | racemic sum (32, `Omeprazole Plasma` observer), enantiomers (23) |
| Dabigatran | prodrug dabigatran etexilate → dabigatran (CES1/CES2) → glucuronide | dabigatran (20), total = free + glucuronide (10, mass-sum observer `SUM`) |
| Warfarin | R- and S-warfarin, simulated separately | enantiomers (33) |
| Itraconazole | parent forms hydroxy-, keto-, N-desalkyl-itraconazole, which inhibit CYP3A4 (auto-inhibition) | parent (63), hydroxy-itraconazole (36) |
| Efavirenz, Erythromycin, Cimetidine, Voriconazole, Rifampicin (Dabigatran) | a co-administered victim drug (midazolam, alfentanil, dabigatran) | DDI arms — the application template (T-31), not this design |

## 2. Harvested facts the design rests on (never invented)

From the snapshots of the models above:

- **Formation**: the parent's simulation process selection carries `MetaboliteName`
  (`{"Name": "CYP3A4-Norverapamil", "MoleculeName": "CYP3A4", "MetaboliteName": "R-Norverapamil"}`); the compound
  process carries `Metabolite`. The metabolite is a full compound in `Compounds` with its own properties and
  processes, listed in the simulation's `Compounds` **without** a `Protocol`.
- **Co-dosing**: each dosed compound has its own protocol (Verapamil: two, the dose split and salt-corrected by the
  modeller: 2 × 55.545 mg for 120 mg verapamil HCl).
- **Interactions** are per compound (`{"Name", "MoleculeName", "CompoundName"}`), so a metabolite's inhibition is
  selected with its own name.
- **Sums** are `ObserverSets` (`Observers[].Formula` over `Organism|<organ>|Plasma|<compound>|Concentration` weighted
  by `Peripheral blood flow fraction`, molar for enantiomers, mass-weighted with MW for Dabigatran's `SUM`), selected
  by the simulation (`ObserverSets: [{"Name": …}]`) and read at
  `Organism|PeripheralVenousBlood|<first compound>|<observer name>` (Verapamil `OutputMappings`).

## 3. Design

### 3.1 The system of record stays the CPF — one per compound — inside a `ModelSystem`

```
ModelSystem (frozen, versioned, content-hashed)
  compounds:  {name: CPF}                      each CPF unchanged in schema and rules
  roles:      {name: parent | metabolite | co-dosed}
  formation:  [(from compound, process key*, to compound)]      * internal name, molecule, data source
  dosing:     {dosed compound: fraction of the study dose}      e.g. R-/S-verapamil 0.462875 each
  analytes:   {name: compound | observer}                       what a study measures
  observers:  {name: ObserverSet document}                      copied verbatim from a published snapshot
```

A single-compound project is a `ModelSystem` with one CPF, parent role, fraction 1, analyte = the compound: every
existing campaign, test and API keeps working unchanged (the wrapper is derived, not stored, for them).

Rejected alternative: one CPF with compound-prefixed ids (`R-Verapamil::elim…`). It breaks the one-compound
invariants of completeness, fitting and provenance, and makes a metabolite parameter look like a parent one.

### 3.2 Studies name their analyte

`StudyRecord.analyte` (default: the parent). The importer maps a dataset's `Molecule` to a compound, or to the
observer the published model maps it onto (`OutputMappings`). Dose stays the reported product dose; the system's
`dosing` fractions split it into the per-compound protocols.

### 3.3 Builder and engine

- Builder: several compounds; `Metabolite` on the process and `MetaboliteName` on the selection; one protocol per
  dosed compound (dose × fraction); interactions of every compound present; `ObserverSets` emitted verbatim and
  selected; outputs: every analyte a simulated study needs.
- Engine (`run_job.R`): profiles keyed by simulation **and** analyte path (today: the first compound only). The bundle
  keeps the parent's profile under the old key, so existing readers are unchanged.
- Round trip (`reference_compare.R`): compares every analyte a pair measures, not only the parent.

### 3.4 Campaign behaviour — phase 1 changes no SME-governed content

- Evaluation judges each study on its analyte with the existing acceptance criteria.
- **Fitting stays on the parent compound** and parent-analyte data, exactly as MS-01 defines the stages today.
  Metabolite and sum studies are evaluated and reported, **not gated and not fitted** in phase 1, because MS-01 has
  no metabolite stage and no metabolite acceptance criteria.
- Enantiomers dosed together (Verapamil, Omeprazole): both are "parent"; the racemic-sum study is judged on the sum.
  Fitting of enantiomer-specific parameters waits for phase 2 (same reason).

### 3.5 Records, reproducibility, Part 11

MAP and MAR carry the `ModelSystem` hash and list compounds, roles, formation links, dose fractions and observers;
each CPF keeps its own version and provenance. The fresh-engine re-run compares every analyte at 1e-6.

## 4. Phases

| Phase | Scope | Needs approval |
|---|---|---|
| 1 | `ModelSystem`; importer builds the full system (all compounds, formation, interactions, dose fractions, observers, analytes); builder + engine + round trip multi-compound; evaluation per analyte (report only for non-parent analytes). Targets: Verapamil, Omeprazole, Dabigatran, Warfarin, Itraconazole round trips exact on PK-Sim | no |
| 2 | Fitting metabolite / enantiomer parameters against their own data; gates for metabolite analytes | **yes** — MS-01 amendment (stage and acceptance for metabolites), SME-governed |
| 3 | Web and API: projects with several compounds, dose fractions entered per compound, analyte per uploaded study | UI review |

## 5. Decisions for the owner

1. **`ModelSystem` wrapper over per-compound CPFs** (recommended) rather than one CPF with prefixed ids.
2. **Dose fractions are required input** for a user-built system (salt factor × enantiomer ratio): never defaulted to
   0.5, because a wrong salt correction biases every exposure by the same factor silently. The importer takes them
   from the published protocols.
3. **Phase 1 reports metabolite / sum analytes without gating them**; gating and fitting them is phase 2 and needs an
   MS-01 amendment you approve (and it stays UNVERIFIED until SME sign-off).
4. **Observer formulas are copied, never composed**: phase 1 supports only sums that exist in a published snapshot.
   A user-defined sum (phase 3) would use one of the harvested shapes (molar sum of enantiomers, MW-weighted sum)
   with compound names substituted, shown for confirmation.

## 6. Risks

- Engine output naming of observers and several compounds' CSV columns must be harvested on the Linux engine before
  the bundle parser relies on it (first CI run of phase 1 does this; nothing is parsed by guess).
- Run time grows with the number of compounds (Verapamil: 4 compounds + 2 observers); fit budgets unchanged in
  phase 1 because only the parent is fitted.
