"""Draft requirement lists per context of use (CoU), drafted from the literature for the owner's review. Inert.

The owner's decision D5 (docs/plans/2026-11-24-data-story-next-phase.md §6 and §11, decided 2026-11-24): "draft the
requirement lists from the literature as UNVERIFIED drafts. They become templates only after my review. Do not change
the locked templates." These files are those drafts. They come from three literature reviews in ``docs/research/``:
``2026-11-24-regulatory-data-by-context-of-use.md`` (the per-CoU tables with R/U/C/O/N statuses), and the PBBM
absorption-inputs and clinical PK data-curation reviews of the same date. Every item cites its sources (PMID, DOI or
guidance name, as the reviews give them) and its note opens with ``UNVERIFIED:``.

What is here:

- ``core.yaml``: the items every CoU starts from (a CoU file may override one, by its id), the five statuses, the
  trigger grammar and the property vocabulary the triggers use (each property with how the Data room determines it);
- one file per CoU: ``ddi_victim``, ``ddi_perpetrator``, ``transporter_ddi``, ``food_effect``, ``pediatric``,
  ``organ_impairment`` (renal and hepatic as two sub-contexts), ``pbbm_bridging_vbe``, ``acid_reducing_agents``,
  ``fih_dose_prediction``, ``special_populations`` (pregnancy, geriatrics, ethnicity);
- ``context_only.yaml``: material kept as context, never a model input and never "missing" (the manufacturing
  process, tablet hardness, the full excipient list, f2), each with why and what it triggers a request for.

Each item has one status for its CoU: REQUIRED, USUALLY_NEEDED (with when it becomes required), CONDITIONAL (with a
trigger in words and as a small structure over the property vocabulary), OPTIONAL or NOT_NEEDED (listed with why).
Where the literature gives no number for a trigger, the trigger says ``threshold: SME`` and none is written.

What is not here, by the ground rules (CLAUDE.md): no PK-Sim name, path or unit; no default value; no acceptance
threshold. The only numbers are a trigger cut-off a cited source states (with ``threshold_source``) and references.

Inert by construction:

- ``modeler_project.requirements.load_templates`` lists ``pbpk_domain.requirements`` only, one level deep; this is a
  sub-package of a sibling package, so no data plan, client request, reconciliation, gate or live template reads them;
- each file's ``applies_to`` is empty, so a loader that found one would select it for no project;
- the Data room may show them, labelled as drafts, but nothing derives a requirement, a "missing" item or a data
  request from them until a draft is promoted.

This package holds data only: nothing here reads the files. Their one reader is
``packages/project-model/tests/test_cou_requirement_drafts.py``, which checks the format, the sources and the
inertness. A summary for review is ``docs/research/2026-11-24-cou-requirement-drafts-for-review.md``. A draft becomes
a template only through a locked-file change (``pbpk_domain/requirements/*.yaml``) with the owner's approval, after the
SME's review, with a version bump.
"""
