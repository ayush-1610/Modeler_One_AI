"""The API's one seam to the agents package (docs/ARCHITECTURE_BOUNDARIES.md, rule B4; `[seams]` in boundaries.toml).

Routers ask this module about the LLM edge and never import `modeler_agents` themselves. Phase 5a moves here what every
agent-assisted page needs first (whether an agent is configured); phase 5b moves the agent jobs (extraction, triage,
research, planning) and their run records.
"""

from __future__ import annotations

from typing import Any


def agents_status() -> dict[str, Any]:
    """Whether an LLM provider is configured, without exposing any key."""
    from modeler_agents.llm import LLMConfigError, chat_model_from_env

    try:
        model = chat_model_from_env()
    except LLMConfigError as exc:
        return {"enabled": False, "problem": str(exc)}
    if model is None:
        return {"enabled": False, "problem": "agents are off (MODELER_LLM_PROVIDER not set): fill the brief by hand"}
    return {"enabled": True, "provider": model.provider, "model": model.model}
