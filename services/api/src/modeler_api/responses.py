"""The standard API response envelope, shared by every router (kept separate to avoid import cycles)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

API_VERSION = "1"


def envelope(data: Any = None, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {"request_id": str(uuid.uuid4()), "timestamp": datetime.now(UTC).isoformat(), "api_version": API_VERSION},
        "errors": errors or [],
    }
