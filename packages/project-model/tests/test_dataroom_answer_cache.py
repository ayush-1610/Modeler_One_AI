"""The Data room's exact answer cache (plan 2026-11-24 §5 item 2): per tenant, found only under exactly its key, never a
near one, and cleared in one call. The stages' use of it is tested with the agents (`services/agents/tests`)."""

from __future__ import annotations

import pytest

from modeler_project.dataroom.answer_cache import CACHE_DIR, AnswerCache, AnswerKey, stable_sha256
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")

KEY = AnswerKey(tenant="t1", stage="extract", prompt_version="dataroom-5", file_sha256="a" * 64, path="d/conc.tsv",
                reader="tsv/1.0.1+csv; lines 2", text_sha256="b" * 64, model="bedrock/anthropic.claude-opus-5-5",
                effort="high", inputs={"question": "c" * 64, "triage": "d" * 64, "focus_chars": "14000", "feedback": ""},
                request_sha256="e" * 64)
ANSWER = {"file": "d/conc.tsv", "tables": [], "facts": [], "not_found": []}


def _cache(root, tenant: str = "t1", project: str = "p1") -> AnswerCache:
    return AnswerCache(Workspace(FileProjectStore(root), tenant, project))


def test_an_answer_is_found_only_under_exactly_its_key(tmp_path):
    cache = _cache(tmp_path)
    kept = cache.put(KEY, ANSWER, author="Claude", identity="bedrock/anthropic.claude-opus-5-5", run="2026-11-24T10:00:00+00:00")
    assert kept is not None and (tmp_path / "t1" / CACHE_DIR / "extract" / f"{KEY.digest()}.json").is_file()
    got = _cache(tmp_path, project="p2").get(KEY)                    # another project of the tenant finds it
    assert got is not None and got.answer == ANSWER and got.project == "p1" and got.author == "Claude"
    assert got.note == "reused: same file, same question, same model (from project p1, run 2026-11-24T10:00:00+00:00)"
    # any input changed: not found, never a "similar" answer
    for change in ({"prompt_version": "dataroom-4"}, {"model": "bedrock/anthropic.claude-sonnet-5-5"}, {"effort": "low"},
                   {"endpoint": "https://other/v1"}, {"reader": "tsv/1.0.2+csv; lines 2"}, {"text_sha256": "f" * 64},
                   {"path": "d/conc (2).tsv"}, {"stage": "check"}, {"request_sha256": "0" * 64},
                   {"inputs": {**KEY.inputs, "question": "0" * 64}}, {"inputs": {**KEY.inputs, "feedback": "1" * 64}}):
        assert cache.get(KEY.model_copy(update=change)) is None, change


def test_another_tenant_never_reads_nor_writes_a_tenants_answers(tmp_path):
    _cache(tmp_path).put(KEY, ANSWER, author="m", identity="m")
    other = _cache(tmp_path, tenant="t2")
    assert other.get(KEY) is None                                    # a key naming t1 is not looked up from t2
    assert other.get(KEY.model_copy(update={"tenant": "t2"})) is None
    assert other.put(KEY, ANSWER, author="m", identity="m") is None  # nor written there
    assert not (tmp_path / "t2" / CACHE_DIR).exists()


def test_an_entry_that_cannot_be_read_or_names_another_key_is_a_miss_and_clearing_empties_it(tmp_path):
    cache = _cache(tmp_path)
    cache.put(KEY, ANSWER, author="m", identity="m")
    path = tmp_path / "t1" / CACHE_DIR / "extract" / f"{KEY.digest()}.json"
    path.write_text(path.read_text().replace('"high"', '"low"'))      # the stored key no longer the asked one
    assert cache.get(KEY) is None
    path.write_text("{not json")
    assert cache.get(KEY) is None
    cache.put(KEY, ANSWER, author="m", identity="m")
    cache.put(KEY.model_copy(update={"stage": "triage"}), {"path": "d/conc.tsv"}, author="m", identity="m")
    assert cache.clear("extract") == 1 and cache.get(KEY) is None
    assert cache.clear() == 1 and cache.clear() == 0
    assert cache.clear("writing") == 0                               # not a cached stage


def test_a_hash_does_not_depend_on_the_order_of_keys():
    assert stable_sha256({"b": 1, "a": [1, "x"]}) == stable_sha256({"a": [1, "x"], "b": 1})
    assert stable_sha256({"a": 1}) != stable_sha256({"a": "1"})
