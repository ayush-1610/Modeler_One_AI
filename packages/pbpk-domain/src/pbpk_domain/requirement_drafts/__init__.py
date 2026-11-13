"""Draft requirement checklists for the sub-domains on the roadmap: biologics, dermal and ocular. Inert.

The owner's decision 2 (2026-11-12) puts biologics, then dermal, then ocular on the roadmap, and no build of one starts
before the owner names a scientist for it (docs/plans/2026-11-12-client-data-intake-redesign.md §7.9; contract
docs/plans/2026-11-12-intake-contracts.md §8.8). Until then each has a draft here: the client data to ask for and how
to check it, written as requirement-template items (the format of ``pbpk_domain.requirements``, with who provides
each item and each condition in words), status ``DRAFT / UNVERIFIED``, every item's note marked ``UNVERIFIED`` with the
scientist it awaits (the file's ``scientist_role``), every PK-Sim location ``TO_HARVEST`` and none given, no CPF id
claimed (every target starts with ``draft.``), no calculator, no default value and no acceptance threshold.

Inert by construction, three times over:

- ``modeler_project.requirements.load_templates`` lists ``pbpk_domain.requirements`` only (one level), and this is a
  sibling package, so no data plan, client request, reconciliation or gate reads these files;
- each draft's ``applies_to`` is empty, so even a loader that found one would select it for no project;
- no APP code is added for them.

This package holds data only: nothing here reads the files. Their one reader is
``packages/project-model/tests/test_requirement_drafts.py``, which checks the format and the inertness. A draft
becomes a template only through a locked-file change (``pbpk_domain/requirements/*.yaml``) with the owner's approval,
after the named scientist has reviewed every item and the PK-Sim locations have been harvested from the engine.
"""
