# Phase 4: one parameter registry in `pbpk_domain` (coupling C1)

Status: **done.** 4a–4d: every table of CPF ids is read from the registry. 4e (the science PR, the owner's decisions of
2026-10-08): registry 1.1, still UNVERIFIED pending SME sign-off.
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
- **4b — done.** `pbpk_domain/parameters/registry.yaml` (v1.0, UNVERIFIED, locked as SME content) and its loader
  `pbpk_domain.parameters`. Tests show that it derives every table exactly and answers, for each of the 101 recorded
  ids, what the code answers:
  - `packages/pbpk-domain/tests/test_parameter_registry.py` covers the pbpk_domain tables, storage family over a
    corpus, the S0 gate against `check_completeness`, and schema validation;
  - `tests/architecture/test_parameter_registry.py` covers the modeler_project tables and the 4a snapshot's answers.

  The drift is reproduced as is, with a `drift:` note on each entry. No consumer reads the registry yet.
- **4c — done:** `inputs` (model/reference ids and prefixes, builder unit, ValueOrigin prefixes, `placement`),
  `evidence` (bounds, `numeric_target`), `completeness` (`check_completeness` reports `parameters.unmet_s0`) and
  `process_bindings.is_process_id` read the registry. An AST test keeps the switched tables from turning back into
  literals. `templates_api._BLANK_PARAMETERS` stays a template's choice; a test checks it meets every S0
  requirement. `plan_api`'s binding group is page layout and stays as it is. The original scope was: `inputs`, `evidence`, `completeness`,
  `process_bindings.is_process_id`, `templates_api`, `plan_api`. The snapshot stays unchanged. The phase 1 vocabulary
  test becomes a registry test.
- **4d — done** (approved by the owner 2026-10-08): `parameter_units._TARGETS` / `target_family`,
  `pksim_paths._COMPOUND_PARAM`, and `cpf.build._PROCESS_FAMILIES` / `REFERENCE_ELIMINATION` read the registry. The
  CLspec message stays in `parameter_units`, because it covers every `.clspec` id with no storage unit. The AST
  guard covers all switched tables. The original scope was:
  **4d — locked consumers** (own PR, owner approval, hashes refreshed): `parameter_units._TARGETS`,
  `pksim_paths._COMPOUND_PARAM`, `build.REFERENCE_ELIMINATION` / `_PROCESS_FAMILIES`. The snapshot stays unchanged.
- **4e — done** (registry 1.1, the owner's decisions of 2026-10-08):
  - (a) the alias, chosen;
  - (b) refusal with its reason, chosen. Harvesting the Individual path is a server task;
  - (c) InVivo for `elim.hepatic.total.*`, chosen.

  The snapshot diff shows exactly these changes. The original scope was:
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
