"""The API's one seam to the orchestrator (docs/ARCHITECTURE_BOUNDARIES.md, rule B4; `[seams]` in boundaries.toml).

Routers ask for a `CampaignRunner` (`runner: RunnerDep`) and never import the orchestrator; tests override
`get_campaign_runner`. The orchestrator is imported on first use, so importing the API stays light.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from modeler_contracts.ports import CampaignRunner


def get_campaign_runner() -> CampaignRunner:
    from modeler_orchestrator.campaign_runner import LocalCampaignRunner

    return LocalCampaignRunner()


RunnerDep = Annotated[CampaignRunner, Depends(get_campaign_runner)]
