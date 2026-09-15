from dataclasses import replace
from datetime import UTC, datetime

import pytest

from modeler_api.compliance.audit import GENESIS_HASH, AuditEvent, ChainedEvent, chain, compute_row_hash, verify_chain
from modeler_api.compliance.signatures import (
    SignatureAuthenticationError,
    SignatureMeaning,
    Signer,
    is_signature_valid,
    sign_record,
)

RECORD_SHA = "a" * 64


def build_chain(n: int) -> list[ChainedEvent]:
    events, prev = [], GENESIS_HASH
    for seq in range(1, n + 1):
        item = chain(
            prev,
            AuditEvent(
                tenant_id="t1",
                seq=seq,
                occurred_at=f"2026-09-15T10:00:0{seq}+00:00",
                actor="user:alice",
                action="UPDATE",
                resource_type="parameter_provenance",
                resource_id="p1",
                before={"value": seq},
                after={"value": seq + 1},
            ),
        )
        events.append(item)
        prev = item.row_hash
    return events


def test_intact_chain_verifies():
    assert verify_chain(build_chain(5)) is None


def test_edited_event_breaks_chain_at_that_index():
    events = build_chain(5)
    tampered = replace(events[2].event, after={"value": 999})
    events[2] = ChainedEvent(event=tampered, prev_hash=events[2].prev_hash, row_hash=events[2].row_hash)
    assert verify_chain(events) == 2


def test_rehashed_edit_still_breaks_next_link():
    events = build_chain(5)
    tampered = replace(events[2].event, after={"value": 999})
    events[2] = ChainedEvent(event=tampered, prev_hash=events[2].prev_hash, row_hash=compute_row_hash(events[2].prev_hash, tampered))
    assert verify_chain(events) == 3


def test_deleted_event_breaks_chain():
    events = build_chain(5)
    del events[1]
    assert verify_chain(events) == 1


class FakeVerifier:
    def __init__(self, ok: bool):
        self.ok = ok

    def verify(self, user_id: str, password: str, second_factor: str) -> bool:
        return self.ok


def test_signature_binds_to_record_hash_and_manifests():
    signature = sign_record(
        signer=Signer(user_id="u1", printed_name="Dr. A. Reviewer"),
        meaning=SignatureMeaning.REVIEWED,
        record_type="m15_table",
        record_id="r1",
        record_sha256=RECORD_SHA,
        password="pw",
        second_factor="123456",
        verifier=FakeVerifier(True),
        clock=lambda: datetime(2026, 9, 15, 12, 30, 5, tzinfo=UTC),
    )
    assert signature.manifestation() == "Dr. A. Reviewer | Reviewed | 2026-09-15 12:30:05 UTC"
    assert is_signature_valid(signature, RECORD_SHA)
    assert not is_signature_valid(signature, "b" * 64)


def test_signature_requires_both_components_and_valid_credentials():
    common = dict(
        signer=Signer(user_id="u1", printed_name="A"),
        meaning=SignatureMeaning.APPROVED,
        record_type="mar",
        record_id="r1",
        record_sha256=RECORD_SHA,
    )
    with pytest.raises(SignatureAuthenticationError):
        sign_record(**common, password="pw", second_factor="", verifier=FakeVerifier(True))
    with pytest.raises(SignatureAuthenticationError):
        sign_record(**common, password="pw", second_factor="1", verifier=FakeVerifier(False))
