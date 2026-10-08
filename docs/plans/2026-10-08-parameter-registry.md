# Phase 4: one parameter registry in `pbpk_domain` (coupling C1)

Status: **4a done (characterization); 4b–4e need the owner's approval** (SME-governed content, locked files).
Sources: `docs/ARCHITECTURE_BOUNDARIES.md` (B1, C1, §6 phase 4), MS-01 §2.2 (`docs/PBPK_MODELING_WORKFLOW.md`).

## Why
A CPF id's meaning is spread over a dozen tables, each a partial copy. The tables:
- `parameter_units._TARGETS` (storage unit)
- `pksim_paths._COMPOUND_PARAM` (PK-Sim compound name)
- `cpf.process_bindings` (process ids)
- `cpf.build` (`REFERENCE_ELIMINATION`, `_PROCESS_FAMILIES`, alternatives)
- `cpf.completeness` (S0)
- `modeler_project.inputs` (`MODEL_IDS`, prefixes, reference ids, placeholders, pathway targets, in-vivo/in-vitro)
- `modeler_project.evidence` (`_PHYSICAL` bounds, `numeric_target`)
- `templates_api._BLANK_PARAMETERS` and `plan_api`

A new id added to one table and not the others has passed every test and produced a model without the value. The
same thing happened once with no clearance at all. Two ids still drift today:
- `elim.hepatic.total_cl` converts to ml/min/kg and satisfies S0's elimination requirement, but nothing places it.
  PK-Sim's `LiverClearance` is bound to `elim.hepatic.total.plasma_clearance`.
- `elim.ehc_fraction` converts, but nothing places it.

## The registry (4b)
`packages/pbpk-domain/src/pbpk_domain/parameters/` holds two pieces:
- `registry.yaml`: data, SME-governed, `status: UNVERIFIED`, versioned, locked.
- A frozen-pydantic loader with the queries the consumers need.

One entry per id or id rule:

| Field | Meaning | Today's source |
|---|---|---|
| `id` / `prefix` | exact id or family rule (`phys.pka.acid.`, `form.`, `sim[`) | the tables above |
| `placement` | `model` (the builder sets it), `process` (harvested process table), `reference` (kept for checks) | `inputs.placement` |
| `kind` | number, text, enum or table | `evidence.numeric_target` |
| `storage` | unit family of MS-01 §2.2, or `not_converted` with the reason (CLspec needs IVIVE) | `parameter_units` |
| `pksim_compound` | harvested compound parameter name (compound-level only) | `pksim_paths._COMPOUND_PARAM` |
| `builder_unit` | unit the snapshot builder checks (`Log Units`) | `inputs._BUILDER_UNIT` |
| `physical_bounds` | review-flag range | `evidence._PHYSICAL` |
| `s0` | which S0 requirement it satisfies, with its label | `cpf.completeness` |
| `origin` | `in_vivo` / `in_vitro` (ValueOrigin method) | `inputs._IN_VIVO` / `_IN_VITRO` |

The registry adds no new science:
- No new id, unit, bound or fit stage.
- Process parameter names and units stay in the harvested process table (`reference.osp_import.PROCESS_PARAMETERS`).
  The registry names the family; it never copies a PK-Sim name it did not harvest.
- Fit stages and bounds stay in MS-01 / `campaign.map`.

## Steps (each one PR to `main`; the characterization snapshot unchanged except in 4e)
- **4a — done.** `tests/architecture/test_parameter_characterization.py` records every table, plus what every
  vocabulary function answers for 101 ids, in `docs/architecture/parameter-vocabulary.json`. The ids come from:
  - every id the tables name;
  - the harvested process table;
  - the requirement templates;
  - the MAP's fit candidates;
  - MS-01 §2.2;
  - edge probes.

  The functions covered: placement, target problem, storage family and conversion, numeric, process id and binding
  candidates, compound path, physical bounds, ValueOrigin method, and the S0 requirement satisfied.
- **4b — registry and equality tests** (new SME-governed, locked file; owner approval). For each table, a test that
  the registry derives it exactly. No consumer changes yet.
- **4c — unlocked consumers derive from the registry:** `inputs`, `evidence`, `completeness`,
  `process_bindings.is_process_id`, `templates_api`, `plan_api`. The snapshot stays unchanged. The phase 1 vocabulary
  test becomes a registry test.
- **4d — locked consumers** (own PR, owner approval, hashes refreshed): `parameter_units._TARGETS`,
  `pksim_paths._COMPOUND_PARAM`, `build.REFERENCE_ELIMINATION` / `_PROCESS_FAMILIES`. The snapshot stays unchanged.
- **4e — the science PR** (owner sign-off; CHANGELOG science entry; the snapshot diff is the review):
  - **`elim.hepatic.total_cl`**: becomes an alias of `elim.hepatic.total.plasma_clearance` (the id MS-01 §2.2 names,
    placed where the OSP models bind it). The S0 message names the placeable id.
  - **`elim.ehc_fraction`**: MS-01 places it on the Individual (`Organism|Liver|EHC continuous fraction`). That path
    must be harvested from a real simulation before anything sets it. Until then it is refused with that reason
    instead of passing as convertible.
  - **ValueOrigin method of total clearances**: `inputs.value_origin_method` files every `elim.hepatic.*` value as
    `InVitro`, including total hepatic plasma clearance, whose MS-01 source is clinical. The owner decides whether it
    is `InVivo`.
- **Not rewritten:** the requirement YAMLs, `campaign.map`'s fit candidates (SME-governed / locked), the A2 prompt and
  `deploy/proof/run_t56.py` (kept unchanged through phase 5). A test checks that every id they name resolves in the
  registry.

## Verification
- Every PR: `make test`, `make lint`, and the characterization snapshot unchanged (4e: changed only as reviewed).
- 4d and 4e: the engine golden tests (CI engine gate). Before 4e merges, a PK-Sim build of a template CPF with total
  hepatic clearance on the server (a result counts only on real PK-Sim).
