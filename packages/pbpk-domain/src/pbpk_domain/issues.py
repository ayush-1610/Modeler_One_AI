from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    """A validation finding. ``code`` is stable and machine-readable; ``message`` is for people."""

    code: str
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} at {self.location}: {self.message}"
