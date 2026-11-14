"""ZIP archives (contracts §6.1, §6.5): members listed with their container, one nested level expanded, the limits, and
an encrypted archive refused with its reason."""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from modeler_intake import synthetic
from modeler_intake.source import parse, parse_document, zip_members
from modeler_intake.source_model import ContainerRef

pytestmark = pytest.mark.req("T-47")


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data)
    return buffer.getvalue()


def test_members_are_parsed_by_their_own_call_with_their_container():
    members = (synthetic.delimited(), synthetic.word_report())
    file = synthetic.zipped(*members, name="batch.zip")
    doc = parse_document(file.data, file.name)
    assert (doc.state, doc.format, doc.parser) == ("read", "zip", "zip")
    assert doc.members == ("concentrations.csv", "design-report.docx")
    assert doc.regions == () and doc.sheets == ()
    sha = hashlib.sha256(file.data).hexdigest()
    for (name, data), member in zip(zip_members(file.data, file.name), members, strict=True):
        assert data == member.data
        container = ContainerRef(sha256=sha, name=file.name, member=name)
        parsed = parse_document(data, name, container=container)
        assert parsed.container == container and parsed.state == "read"
        assert parsed.file_sha256 == hashlib.sha256(member.data).hexdigest()       # a member is its own document


def test_one_nested_level_is_expanded_and_a_deeper_zip_stays_a_member():
    inner = synthetic.zipped(synthetic.delimited(), name="inner.zip")
    deepest = _zip({"deep.csv": b"a,b\r\n1,2\r\n"})
    middle = _zip({"deeper.zip": deepest, "notes.txt": b"Study 230-23 notes\n"})
    outer = _zip({"inner.zip": inner.data, "middle.zip": middle, "design-report.docx": synthetic.word_report().data})
    names = [name for name, _data in zip_members(outer, "outer.zip")]
    assert names == ["inner.zip/concentrations.csv", "middle.zip/deeper.zip", "middle.zip/notes.txt", "design-report.docx"]
    doc = parse_document(outer, "outer.zip")
    assert doc.members == tuple(names)
    deeper = dict(zip_members(outer, "outer.zip"))["middle.zip/deeper.zip"]
    assert parse_document(deeper, "middle.zip/deeper.zip").members == ("deep.csv",)       # parsed by its own call
    assert parse_document(dict(zip_members(outer, "outer.zip"))["inner.zip/concentrations.csv"],
                          "inner.zip/concentrations.csv").sheets[0].name == "concentrations"


def test_the_limits_refuse_an_archive_with_the_limit_named(monkeypatch):
    data = _zip({f"m{k}.txt": b"x" * 100 for k in range(4)})
    with pytest.raises(ValueError, match="more than 3 members"):
        parse.archive.zip_members(data, "many.zip", max_members=3)
    with pytest.raises(ValueError, match="over the limit of 50 per member"):
        parse.archive.zip_members(data, "big.zip", max_member_bytes=50)
    with pytest.raises(ValueError, match="in all"):
        parse.archive.zip_members(data, "heavy.zip", max_total_bytes=250)
    monkeypatch.setattr(parse, "MAX_MEMBERS", 3)
    doc = parse_document(data, "many.zip")
    assert doc.state == "unreadable" and "more than 3 members" in doc.reason and doc.members == ()
    assert (parse.MAX_MEMBER_BYTES, parse.MAX_TOTAL_BYTES) == (250 * 1024 * 1024, 1024 ** 3)


def test_a_member_that_inflates_past_its_stated_size_is_stopped_at_the_limit():
    data = bytearray(_zip({"bomb.txt": b"0" * 10_000}))
    for signature, offset in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):          # state a size of 10 bytes, both headers
        at = data.index(signature)
        data[at + offset:at + offset + 4] = (10).to_bytes(4, "little")
    with pytest.raises(ValueError):
        parse.archive.zip_members(bytes(data), "bomb.zip", max_member_bytes=1000)


def test_an_encrypted_zip_is_unreadable_with_its_reason():
    data = bytearray(_zip({"secret.csv": b"a,b\r\n1,2\r\n"}))
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):            # set the encryption flag in both headers
        at = data.index(signature)
        data[at + offset] |= 0x01
    with pytest.raises(ValueError, match="encrypted"):
        zip_members(bytes(data), "secret.zip")
    doc = parse_document(bytes(data), "secret.zip")
    assert doc.state == "unreadable" and "secret.csv is encrypted" in doc.reason


def test_a_damaged_archive_is_unreadable_not_an_exception():
    file = synthetic.zipped(synthetic.delimited(), synthetic.word_report())
    for broken in (file.data[:60], file.data[:-10], b"not a zip"):
        doc = parse_document(broken, "broken.zip")
        assert doc.state == "unreadable" and doc.reason
    empty = parse_document(b"PK\x05\x06" + b"\x00" * 18, "empty.zip")              # a valid archive with nothing in it
    assert (empty.state, empty.members) == ("read", ())


def test_the_metadata_an_operating_system_adds_is_not_a_member():
    data = _zip({"listing.csv": b"a,b\r\n1,2\r\n", "__MACOSX/._listing.csv": b"\x00\x05\x16\x07 resource fork",
                 "__MACOSX/inner/._x.csv": b"\x00", "folder/.DS_Store": b"\x00\x00\x00\x01Bud1"})
    assert [name for name, _data in zip_members(data, "mac.zip")] == ["listing.csv"]
    assert parse_document(data, "mac.zip").members == ("listing.csv",)
