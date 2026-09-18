"""Electronic signatures (21 CFR 11.50, 11.70, 11.200; feature F-403).

- 11.50: the manifestation carries printed name, date/time (UTC) and meaning.
- 11.70: the signature is bound to the SHA-256 of the signed record; any later change invalidates it.
- 11.200: both identification components (password and second factor) are re-verified at every signing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol


class SignatureMeaning(StrEnum):
    AUTHORED = "Authored"
    REVIEWED = "Reviewed"
    APPROVED = "Approved"
    QA_RELEASED = "QA Released"


class SignatureAuthenticationError(PermissionError):
    pass


class StepUpVerifier(Protocol):
    """Verifies credentials against the identity provider (Keycloak) without creating a session."""

    def verify(self, user_id: str, password: str, second_factor: str) -> bool: ...


@dataclass(frozen=True)
class Signer:
    user_id: str
    printed_name: str


@dataclass(frozen=True)
class Signature:
    signature_id: str
    signer_id: str
    printed_name: str
    meaning: SignatureMeaning
    signed_at: datetime
    record_type: str
    record_id: str
    record_sha256: str
    auth_method: str

    def manifestation(self) -> str:
        return f"{self.printed_name} | {self.meaning} | {self.signed_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"


def sign_record(
    *,
    signer: Signer,
    meaning: SignatureMeaning,
    record_type: str,
    record_id: str,
    record_sha256: str,
    password: str,
    second_factor: str,
    verifier: StepUpVerifier,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Signature:
    if not password or not second_factor:
        raise SignatureAuthenticationError("both identification components are required to sign")
    if len(record_sha256) != 64:
        raise ValueError("record_sha256 must be a hex SHA-256 digest")
    if not verifier.verify(signer.user_id, password, second_factor):
        raise SignatureAuthenticationError("signature credentials rejected")
    return Signature(
        signature_id=str(uuid.uuid4()),
        signer_id=signer.user_id,
        printed_name=signer.printed_name,
        meaning=meaning,
        signed_at=clock().astimezone(UTC),
        record_type=record_type,
        record_id=record_id,
        record_sha256=record_sha256,
        auth_method="password+totp",
    )


def sign_after_step_up(
    *,
    signer: Signer,
    meaning: SignatureMeaning,
    record_type: str,
    record_id: str,
    record_sha256: str,
    acr: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Signature:
    """Sign when the identity provider has already re-verified both factors as a step-up (OIDC ``acr``).

    Used with token-based auth (T-06): the caller has checked ``acr=loa2`` and a fresh ``auth_time`` before
    calling, so the two identification components (11.200) were re-verified at Keycloak within the step-up
    window rather than passed to us."""
    if len(record_sha256) != 64:
        raise ValueError("record_sha256 must be a hex SHA-256 digest")
    return Signature(
        signature_id=str(uuid.uuid4()),
        signer_id=signer.user_id,
        printed_name=signer.printed_name,
        meaning=meaning,
        signed_at=clock().astimezone(UTC),
        record_type=record_type,
        record_id=record_id,
        record_sha256=record_sha256,
        auth_method=f"oidc:{acr}",
    )


def is_signature_valid(signature: Signature, current_record_sha256: str) -> bool:
    return signature.record_sha256 == current_record_sha256
