"""The Data room's run (plan 2026-11-21 v2 §5 step 2, §9): read the delivery, then the five agents, each on the model
the admin console chose for it (A6 the question, A7 sorts the files, A8 extracts, A9 checks, A10 writes), every answer
checked by code before it counts (`modeler_project.dataroom`).

    run_room(store, chat_for=lambda agent: model_or_None, actor="user:…")

`chat_for(agent)` gives the chat model for "A6" … "A10", or None (no model set up: that stage is skipped and says so;
what code does alone still runs), or why a chosen model cannot be used (the run pauses there). The run's progress is the
store's `run.json` (`RUN_STAGES`), written after each step, so a page polling `store.run()` shows live counts. Each
stage's answers are kept per file (by its sha256): a second run redoes only what is missing, unless `redo` names the
stage. Across the tenant's projects, a file triaged, extracted or checked before with every input the same is answered
from the tenant's answer cache with no model call (`modeler_project.dataroom.answer_cache`; plan 2026-11-24 §5). A run
that stops for a reason that passes (a provider down or rate-limited, a paid model's cap, a model that cannot be used)
is paused, not failed, and `run_room(..., resume=…)` goes on where it stopped (plan 2026-11-24 §4).
"""

from __future__ import annotations

from modeler_agents.dataroom.run import PER_FILE, REST_MINUTES, RUN_STAGES, WHERE, RunPaused, run_room

__all__ = ["PER_FILE", "REST_MINUTES", "RUN_STAGES", "WHERE", "RunPaused", "run_room"]
