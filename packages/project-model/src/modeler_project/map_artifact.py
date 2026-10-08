"""The signed Model Analysis Plan as an artifact (MAP/main): the kind's one writer and reader (phase 6e, rule B3).

P5's `plan:sign` generates the MAP from the approved model plan (`pbpk_domain.campaign.map`), signs it (Part 11, from
the token's step-up) and records it here with the campaign inputs it staged. The plan page and blinding (D-15: external
values stay hidden until the MAP is signed) read it through this module, never from the stored JSON.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict

from modeler_project.artifacts import ArtifactKind, ArtifactRef, ArtifactVersion
from modeler_project.workspace import Workspace
from pbpk_domain.campaign.map import MapDocument

MAIN = "main"


class MapSignature(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signature_id: str
    manifestation: str


class MapArtifact(BaseModel):
    """MAP/main's content: the MAP document as signed, its content hash, the signature and the staged campaign inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    map: dict[str, Any]                     # MapDocument as JSON (`document()` parses it)
    map_sha256: str
    signature: MapSignature | None = None
    campaign: dict[str, Any] | None = None  # the staged inputs a campaign starts from (cpf, map, observed URIs)

    @property
    def signed(self) -> bool:
        return self.signature is not None

    def document(self) -> MapDocument:
        return MapDocument.model_validate(self.map)

    def to_content(self) -> dict[str, Any]:
        # only the keys that were set: a stored version reads back byte for byte (the audit chain hashes content)
        return self.model_dump(mode="json", exclude_unset=True)

    @classmethod
    def from_content(cls, content: dict[str, Any]) -> MapArtifact:
        return cls.model_validate(content)


def latest_map(ws: Workspace) -> tuple[ArtifactVersion, MapArtifact] | None:
    version = ws.latest(ArtifactKind.MAP, MAIN)
    return (version, MapArtifact.from_content(version.content)) if version else None


def signed_map(ws: Workspace) -> tuple[ArtifactVersion, MapArtifact] | None:
    """The latest MAP when it carries a signature (a newer plan version makes it stale, not unsigned)."""
    latest = latest_map(ws)
    return latest if latest is not None and latest[1].signed else None


def record_signed_map(ws: Workspace, artifact: MapArtifact, *, derived_from: Iterable[ArtifactRef], actor: str,
                      reason: str) -> ArtifactVersion:
    return ws.commit(ArtifactKind.MAP, MAIN, artifact.to_content(), derived_from=derived_from, actor=actor, reason=reason)
