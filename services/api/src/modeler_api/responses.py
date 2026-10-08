"""The standard API response envelope, shared by every router (kept separate to avoid import cycles).

`envelope()` builds the body; `Envelope[T]` describes it for a typed route (phase 6, rule B2), and `answers(T)` gives a
route's decorator both: `@router.get(path, **answers(BriefPage))`. The escalation routes answer without the envelope
(kept as they are, the owner's choice of 2026-10-08): `answers_without_envelope(T)`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

API_VERSION = "1"


def envelope(data: Any = None, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {"request_id": str(uuid.uuid4()), "timestamp": datetime.now(UTC).isoformat(), "api_version": API_VERSION},
        "errors": errors or [],
    }


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    timestamp: str
    api_version: str


class ErrorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    location: str | None = None


class Envelope[T](BaseModel):
    """Every JSON answer: `data` (the page or the result), `meta`, `errors` (empty on success)."""

    model_config = ConfigDict(extra="forbid")

    data: T
    meta: Meta
    errors: list[ErrorItem]


def answers(model: Any) -> dict[str, Any]:
    """A route's decorator arguments for an answer built with `envelope(...)`: the typed envelope, and only the keys
    the handler set (an optional key the handler left out stays out, so typing never changes an answer)."""
    return {"response_model": Envelope[model], "response_model_exclude_unset": True}


def answers_without_envelope(model: Any) -> dict[str, Any]:
    """As `answers`, for a route whose answer is the object itself, with no envelope."""
    return {"response_model": model, "response_model_exclude_unset": True}
