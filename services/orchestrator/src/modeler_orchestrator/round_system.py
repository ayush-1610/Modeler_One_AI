"""A model system's state beside each campaign CPF version (multi-compound phase 2, D-20).

A campaign's round state is one CPF: every round, post-fit pass, joint fit and feedback decision reads `cpf_uri` and
writes the next CPF version beside it. In a model system a fit may also move another compound's parameter (a
metabolite's clearance, a co-parent enantiomer's), and that compound's CPF lives in the system document. So the round
state stays one URI:

- each new CPF version of a system campaign has the system as of that version written beside it
  (``<cpf file stem>.system.json``, `write_beside`);
- a version that moved another compound names that compound's new version and content hash in its note
  (`moved_note`), so the CPF's own sha256 binds the system it was written with;
- a CPF with no system beside it (the campaign's first, or a single-compound campaign) uses the campaign's starting
  system (`system_uri`), as before.

Each compound's CPF stays the record of its own parameters, with its own version and provenance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from pbpk_domain.atomic_io import atomic_write_bytes

if TYPE_CHECKING:
    from pbpk_domain.cpf import CPF
    from pbpk_domain.system import ModelSystem


def _local(uri: str) -> Path | None:
    parsed = urlparse(uri)
    return Path(unquote(parsed.path)) if parsed.scheme == "file" else None


def beside(cpf_path: Path) -> Path:
    return cpf_path.with_name(f"{cpf_path.stem}.system.json")


def current_system_uri(cpf_uri: str, system_uri: str) -> str:
    """The system document as of `cpf_uri`: the one beside it, else the campaign's starting one ("" for one compound)."""
    if not system_uri:
        return ""
    path = _local(cpf_uri)
    if path is not None and beside(path).exists():
        return beside(path).as_uri()
    return system_uri


def round_system(cpf_uri: str, system_uri: str, cpf: CPF) -> ModelSystem | None:
    """The system as of `cpf_uri` with `cpf` as its fitted compound, or None for one compound (or not loadable here)."""
    path = _local(current_system_uri(cpf_uri, system_uri))
    if path is None or not path.exists():
        return None
    from pbpk_domain.system import ModelSystem, with_cpf

    return with_cpf(ModelSystem.model_validate_json(path.read_text(encoding="utf-8")), cpf)


def write_beside(cpf_path: Path, system: ModelSystem) -> None:
    atomic_write_bytes(beside(cpf_path), system.model_dump_json().encode("utf-8"))


def carry_forward(old_cpf_uri: str, new_cpf_path: Path, system_uri: str, cpf: CPF) -> None:
    """Write the system as of `old_cpf_uri`, with `cpf` in it, beside a new CPF version (nothing for one compound)."""
    system = round_system(old_cpf_uri, system_uri, cpf)
    if system is not None:
        write_beside(new_cpf_path, system)


def content_sha256(cpf: CPF) -> str:
    """A CPF's content hash, without its timestamp (as `ModelSystem.sha256` hashes its compounds)."""
    doc = cpf.model_dump(mode="json", exclude={"created_at"})
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def moved_note(moved: list[CPF]) -> str:
    return "; ".join(f"{c.compound} v{c.version} (sha256 {content_sha256(c)[:12]})" for c in moved)
