"""Per-tenant choice of where Claude runs (data residency, architecture pack §6.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic


class AgentsDisabledError(RuntimeError):
    pass


@dataclass(frozen=True)
class TenantLLMPolicy:
    provider: Literal["anthropic", "bedrock", "vertex", "self_hosted", "disabled"] = "disabled"
    region: str | None = None
    gcp_project_id: str | None = None
    inference_geo: str | None = None  # first-party API only
    base_url: str | None = None  # self_hosted: an endpoint that implements the Anthropic Messages API
    model: str | None = None  # self_hosted: the model name served there


@dataclass(frozen=True)
class LLMConfig:
    client: Any
    async_client: Any
    model: str
    request_options: dict[str, Any] = field(default_factory=dict)  # accepted by every Messages call
    beta_options: dict[str, Any] = field(default_factory=dict)  # only for client.beta.* calls


def make_llm(policy: TenantLLMPolicy) -> LLMConfig:
    if policy.provider == "anthropic":
        return LLMConfig(
            client=anthropic.Anthropic(),
            async_client=anthropic.AsyncAnthropic(),
            model="claude-opus-5",
            request_options={"inference_geo": policy.inference_geo} if policy.inference_geo else {},
            # Server-side refusal fallback: the API retries a declined request on a fallback model.
            beta_options={"betas": ["server-side-fallback-2026-07-01"], "extra_body": {"fallbacks": "default"}},
        )
    if policy.provider == "bedrock":
        if not policy.region:
            raise ValueError("Bedrock requires a region")
        return LLMConfig(
            client=anthropic.AnthropicBedrockMantle(aws_region=policy.region),
            async_client=anthropic.AsyncAnthropicBedrockMantle(aws_region=policy.region),
            model="anthropic.claude-opus-5",
        )
    if policy.provider == "vertex":
        if not policy.gcp_project_id:
            raise ValueError("Vertex AI requires a GCP project id")
        region = policy.region or "global"
        return LLMConfig(
            client=anthropic.AnthropicVertex(project_id=policy.gcp_project_id, region=region),
            async_client=anthropic.AsyncAnthropicVertex(project_id=policy.gcp_project_id, region=region),
            model="claude-opus-5",
        )
    if policy.provider == "self_hosted":
        # For the planned locally hosted model. Tool use and structured outputs work only if the server
        # implements those parts of the Messages API; agent evals must pass on it before a tenant switches.
        if not policy.base_url or not policy.model:
            raise ValueError("self_hosted requires base_url and model")
        return LLMConfig(
            client=anthropic.Anthropic(base_url=policy.base_url),
            async_client=anthropic.AsyncAnthropic(base_url=policy.base_url),
            model=policy.model,
        )
    raise AgentsDisabledError("LLM agents are disabled for this tenant")
