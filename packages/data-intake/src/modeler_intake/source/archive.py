"""ZIP archives: their file members, one level of nested ZIP, within limits (contracts §6.1).

Each member is its own document: the caller parses it by its own call with a `ContainerRef`. A member that is itself a
ZIP is opened once more (its members are listed as `<inner.zip>/<member>`); a ZIP inside that one is a plain member.
Nothing is written to disk: member names are labels, never paths. The metadata an operating system adds when it makes
an archive (a `__MACOSX/` resource fork, a `.DS_Store` folder view) is not a member: it holds no client content. An
encrypted member, a member over the size limit, too many members or too many bytes in all is a `ValueError` naming the
limit, so a refused archive is `unreadable` with that reason, never partly read in silence.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from modeler_intake.documents import MAX_BYTES

MAX_MEMBERS = 500
MAX_MEMBER_BYTES = MAX_BYTES
MAX_TOTAL_BYTES = 1024 ** 3
_CHUNK = 1024 * 1024


class _Budget:
    """What one expansion may still read (members and bytes), shared with the nested level."""

    def __init__(self, members: int, total: int, member_bytes: int):
        self.members, self.max_members = members, members
        self.total, self.max_total = total, total
        self.member_bytes = member_bytes


def is_zip_name(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() == ".zip"


def is_metadata(name: str) -> bool:
    """An operating system's own entry in an archive: a macOS resource fork or folder view."""
    path = PurePosixPath(name.replace("\\", "/"))
    return path.parts[:1] == ("__MACOSX",) or path.name == ".DS_Store"


def zip_members(data: bytes, filename: str, *, max_members: int = MAX_MEMBERS, max_member_bytes: int = MAX_MEMBER_BYTES,
                max_total_bytes: int = MAX_TOTAL_BYTES) -> list[tuple[str, bytes]]:
    """Every file member (name, bytes), a nested ZIP's members expanded once; ValueError for an encrypted member, a
    corrupt archive or a limit passed (the limits are the module's; the keywords exist for tests)."""
    budget = _Budget(max_members, max_total_bytes, max_member_bytes)
    return _expand(data, filename, prefix="", budget=budget, nested=False)


def _expand(data: bytes, filename: str, *, prefix: str, budget: _Budget, nested: bool) -> list[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except Exception as exc:  # zipfile raises many types for a damaged archive
        raise ValueError(f"{filename}: not a readable ZIP archive ({type(exc).__name__}: {exc})") from exc
    out: list[tuple[str, bytes]] = []
    for info in infos:
        if info.is_dir() or is_metadata(info.filename):
            continue
        name = prefix + info.filename
        if info.flag_bits & 0x1:
            raise ValueError(f"{filename}: the member {name} is encrypted; an encrypted ZIP cannot be read")
        if info.file_size > budget.member_bytes:
            raise ValueError(f"{filename}: the member {name} holds {info.file_size} bytes, over the limit of "
                             f"{budget.member_bytes} per member")
        member = _read(archive, info, name, filename, budget)
        if not nested and is_zip_name(info.filename):
            out += _expand(member, name, prefix=name + "/", budget=budget, nested=True)
            continue
        budget.members -= 1
        if budget.members < 0:
            raise ValueError(f"{filename}: more than {budget.max_members} members, the limit")
        out.append((name, member))
    return out


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, name: str, filename: str, budget: _Budget) -> bytes:
    """A member's bytes, read in chunks so a member that inflates past its stated size is stopped at the limit."""
    limit = min(budget.member_bytes, budget.total)
    buffer = io.BytesIO()
    try:
        with archive.open(info) as handle:
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                buffer.write(chunk)
                if buffer.tell() > limit:
                    which = "per member" if limit == budget.member_bytes else "in all"
                    raise ValueError(f"{filename}: the member {name} inflates past the limit of {limit} bytes {which}")
    except ValueError:
        raise
    except Exception as exc:  # zlib, lzma, bz2 and zipfile raise many types for a damaged member
        raise ValueError(f"{filename}: the member {name} cannot be read ({type(exc).__name__}: {exc})") from exc
    budget.total -= buffer.tell()
    if budget.total < 0:
        raise ValueError(f"{filename}: the members hold more than {budget.max_total} bytes in all, the limit")
    return buffer.getvalue()
