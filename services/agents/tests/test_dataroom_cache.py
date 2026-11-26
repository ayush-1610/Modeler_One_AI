"""The Data room's answer cache and cache-friendly prompt order (plan 2026-11-24 §5 items 2 and 3), with a recording fake
model: no model is ever called. The delivery is the made-up Exampleamide one (`modeler_project.dataroom.synthetic`) and
the fake answers what Nemotron Ultra once submitted for it (the anonymized CI fixture
`packages/project-model/tests/fixtures/dataroom/exampleamide-recorded.json`), the same answer for the same file every
time. Those answers were recorded before code's checks were tightened, so 5 of the 9 extractions hold facts (and one a
table) code now refuses: the fake then does what the submit tool asks, leaves out what code refused and submits again,
which leaves 6 files with a table for the checker.

The measure: a second run of the same delivery in a new project of the same tenant asks the model nothing for triage
(A7), extraction (A8) or the check (A9); the question card (A6) and the writing (A10) are asked again. Another tenant
reuses nothing.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from modeler_agents.dataroom import run_room
from modeler_agents.llm import CACHE_PREFIX, ChatResult, ToolCall
from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom.answer_cache import CACHE_DIR, AnswerCache
from modeler_project.dataroom.synthetic import delivery
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")

RECORDED = json.loads((Path(__file__).resolve().parents[3] / "packages" / "project-model" / "tests" / "fixtures" / "dataroom"
                       / "exampleamide-recorded.json").read_text())
AGENTS = {"submit_question": "A6 question", "submit_triage": "A7 triage", "submit_extraction": "A8 extract",
          "submit_review": "A9 check", "submit_writing": "A10 write"}
PER_FILE = ("A7 triage", "A8 extract", "A9 check")
_FILE = re.compile(r"^File: (.+?)(?: \(|$)", re.MULTILINE)


def _left_out(submit: str, answer: dict[str, Any], said: str) -> dict[str, Any]:
    """The answer without what the submit tool's problems name: what a model does when told "fix them and submit again
    (or leave out what cannot be fixed)"."""
    problems = [ln[2:] for ln in said.splitlines() if ln.startswith("- ")]
    if submit == "submit_extraction":
        tables = {int(m.group(1)) for p in problems if (m := re.match(r"table (\d+)\b", p))}
        return {**answer, "tables": [t for i, t in enumerate(answer.get("tables", []), start=1) if i not in tables],
                "facts": [f for f in answer.get("facts", [])
                          if not any(p.startswith(f"fact {f['field']} = {f['value']!r}:") for p in problems)]}
    if submit == "submit_question":
        return {**answer, "quotes": [q for q in answer.get("quotes", [])
                                     if not any(p.startswith(f"quote for {q['field']}:") for p in problems)]}
    if submit == "submit_writing":
        bad = {p.split(": a number", 1)[0] for p in problems}
        return {k: {key: v for key, v in answer[k].items() if key not in bad} for k in ("findings", "requests")}
    return answer


class Recording:
    """A fake model: it answers each agent with the recorded submission for the file its task names (leaving out, and
    submitting again, what code refused; `corrects=False`: says DONE whatever the answer), and records every request it
    is sent (its instructions, tools and task)."""

    provider, model = "recorded", "nemotron-replay"

    def __init__(self, review_issue: str = "", corrects: bool = True):
        self.calls: Counter[str] = Counter()
        self.files: dict[str, set[str]] = {a: set() for a in AGENTS.values()}
        self.requests: list[dict[str, Any]] = []
        self.review_issue = review_issue
        self.corrects = corrects

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult:
        submit = next(t["function"]["name"] for t in tools if t["function"]["name"].startswith("submit_"))
        agent, task = AGENTS[submit], messages[1]
        self.calls[agent] += 1
        if found := _FILE.search(task["content"]):
            self.files[agent].add(found.group(1))
        self.requests.append({"agent": agent, "system": messages[0]["content"], "tools": json.dumps(tools),
                              "task": task["content"], "shared": task.get(CACHE_PREFIX, 0)})
        said = str(messages[-1].get("content", "")) if messages[-1]["role"] == "tool" else ""
        answer = self.answer(submit, task["content"])
        if said.startswith("saved"):
            before = json.loads(messages[-2]["tool_calls"][0]["function"]["arguments"])
            answer = _left_out(submit, before, said) if self.corrects else before
            if "problems" not in said or answer == before:
                return ChatResult(content="DONE", tool_calls=(), finish_reason="stop", usage={}, model=self.model)
        return ChatResult(content="", tool_calls=(ToolCall(id=f"c{len(self.requests)}", name=submit, arguments=answer,
                                                           raw_arguments=json.dumps(answer)),),
                          finish_reason="tool_calls", usage={}, model=self.model)

    def answer(self, submit: str, task: str) -> dict[str, Any]:
        if submit == "submit_question":
            return RECORDED["question"]
        if submit == "submit_writing":
            return RECORDED["writing"]
        path = _FILE.search(task).group(1)  # type: ignore[union-attr]
        if submit == "submit_triage":
            return RECORDED["triage"][path]
        if submit == "submit_extraction":
            return RECORDED["extractions"][path]
        tables = len(re.findall(r"^Table \d+ \(", task, re.MULTILINE))
        return {"tables": [{"table": i, "ok": not self.review_issue, "issue": self.review_issue}
                           for i in range(1, tables + 1)]}

    def asked(self, agent: str) -> int:
        """Files the agent was asked about."""
        return len(self.files[agent])


def _project(root: Path, tenant: str, project: str) -> DataRoomStore:
    store = DataRoomStore(Workspace(FileProjectStore(root), tenant, project))
    for name, data in delivery().items():
        store.add_upload(name, data, by="user:m")
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    return store


def _run(store: DataRoomStore, model: Recording, **kw: Any) -> dict[str, Any]:
    doc = run_room(store, chat_for=lambda agent: model, actor="user:m", use_ocr=False,
                   stages=["question", "triage", "extract", "check", "write"], **kw)
    assert doc["state"] == "done", doc["error"]
    return doc


def test_a_second_run_of_the_same_delivery_in_a_new_project_of_the_tenant_asks_no_model_to_triage_extract_or_check(
        tmp_path):
    first, second, other = Recording(), Recording(), Recording()
    a = _project(tmp_path, "t1", "p1")
    _run(a, first)
    b = _project(tmp_path, "t1", "p2")
    doc = _run(b, second)
    c = _project(tmp_path, "t2", "p1")                 # another tenant: nothing is shared
    _run(c, other)

    table = "\n".join(f"{s:12} first run {first.calls[s]:3} calls, {first.asked(s):2} files   "
                      f"second run, new project {second.calls[s]:3} calls, {second.asked(s):2} files   "
                      f"another tenant {other.calls[s]:3} calls" for s in AGENTS.values())
    print("\nModel calls per agent on the Exampleamide delivery (10 files, 9 used, 6 with a table code accepts):\n" + table)
    assert (first.asked("A7 triage"), first.asked("A8 extract"), first.asked("A9 check")) == (10, 9, 6), table
    assert [second.calls[s] for s in PER_FILE] == [0, 0, 0], table
    assert second.calls["A6 question"] == first.calls["A6 question"] > 0      # not cached: the card is drafted again
    assert second.calls["A10 write"] == first.calls["A10 write"] > 0
    assert other.calls == first.calls, table                                    # never across tenants

    # the second project's room holds the same answers, each said to be reused, with the model that wrote it
    assert {f.path: f.triage for f in b.files()} == {f.path: f.triage for f in a.files()}
    assert b.extractions() == a.extractions() and b.reviews() == a.reviews()
    notes = {(x["stage"], x["file"]): x for x in b.authors() if x["stage"] in ("triage", "extract", "check")}
    assert len(notes) == 10 + 9 + 6
    assert all(x["model"] == "recorded/nemotron-replay" and x["identity"] == "recorded/nemotron-replay"
               and x["note"].startswith("reused: same file, same question, same model (from project p1, run 20")
               for x in notes.values())
    assert any(s["type"] == "answer_reused" and s["from_project"] == "p1" for s in b.agent_steps())
    note = {s["id"]: s["note"] for s in doc["stages"]}
    assert note["triage"] == "10 files sorted; 10 answered from an earlier run (same file, same question, same model: no model call)"
    sha = next(f.sha256 for f in b.files() if f.path.endswith("EX-01 concentrations.tsv"))
    assert b.extraction(sha)[1]["reused"].startswith("reused: same file")    # type: ignore[index]
    # the cache sits with the tenant, not with a project
    assert (tmp_path / "t1" / CACHE_DIR / "extract").is_dir() and (tmp_path / "t2" / CACHE_DIR / "extract").is_dir()
    assert not (tmp_path / "t1" / "projects" / "p1" / CACHE_DIR).exists()


def test_every_file_of_a_delivery_starts_its_request_with_the_same_instructions_tools_and_delivery_block(tmp_path):
    model = Recording()
    _run(_project(tmp_path, "t1", "p1"), model)
    for agent in PER_FILE:
        files = {_FILE.search(r["task"]).group(1): r for r in model.requests if r["agent"] == agent}  # type: ignore[union-attr]
        assert len(files) >= 6, agent
        (one, a), (two, b) = list(files.items())[:2]
        assert a["system"] == b["system"] and a["tools"] == b["tools"], agent    # byte for byte
        assert one not in a["system"] + a["tools"] and two not in b["system"] + b["tools"], agent
        # the delivery's block first, the same for both (and marked as the shared start); the file's own block last
        assert a["task"][: a["shared"]] == b["task"][: b["shared"]], agent
        assert one in a["task"][a["shared"]:] and two in b["task"][b["shared"]:], agent
    extract = next(r for r in model.requests if r["agent"] == "A8 extract")
    assert extract["task"].startswith("The question: ") and extract["shared"] > 0
    assert extract["task"][: extract["shared"]].endswith("\n\n") and "File: " not in extract["task"][: extract["shared"]]
    assert "Table kinds (kind: the roles of its columns) for this file" in extract["task"][extract["shared"]:]
    assert "study.dose" not in extract["system"]           # no field list in the instructions: it is the file's
    triage = next(r for r in model.requests if r["agent"] == "A7 triage")
    assert triage["task"][: triage["shared"]] == f"The question: {RECORDED['question']['question']}\n"


def test_an_answer_code_still_refuses_is_not_kept_and_a_redo_asks_the_model_again(tmp_path):
    class Refused(Recording):            # never corrects: the recorded answers, problems and all
        def __init__(self) -> None:
            super().__init__(corrects=False)

    a = _project(tmp_path, "t1", "p1")
    _run(a, Refused())
    b = _project(tmp_path, "t1", "p2")
    again = Refused()
    _run(b, again)
    assert again.asked("A8 extract") == 5            # the five answers code refused facts of: asked again, never kept
    assert again.asked("A7 triage") == 0
    redo = Recording()
    _run(b, redo, redo=["triage"])
    assert redo.asked("A7 triage") == 10              # asked to redo: the model is asked, not the cache


def test_the_key_holds_the_question_and_the_model(tmp_path):
    a = _project(tmp_path, "t1", "p1")
    _run(a, Recording())

    class Other(Recording):
        provider, model = "recorded", "another-model"

    b = _project(tmp_path, "t1", "p2")
    other = Other()
    _run(b, other)
    assert [other.asked(s) for s in PER_FILE] == [10, 9, 6]          # another model: asked again

    class Reworded(Recording):
        def answer(self, submit: str, task: str) -> dict[str, Any]:
            got = super().answer(submit, task)
            return {**got, "question": got["question"] + " (reworded)"} if submit == "submit_question" else got

    c = _project(tmp_path, "t1", "p3")
    reworded = Reworded()
    _run(c, reworded)
    assert [reworded.asked(s) for s in PER_FILE] == [10, 9, 0]       # another question: triage and extraction asked
    # again; the check's prompt holds no question, and the extraction it is shown is the same: reused
    cleared = AnswerCache(Workspace(FileProjectStore(tmp_path), "t1", "p1")).clear()
    assert cleared == (10 + 9 + 6) * 2 + 10 + 9                      # every answer kept: by model, by question
    again = Recording()
    _run(_project(tmp_path, "t1", "p4"), again)
    assert [again.asked(s) for s in PER_FILE] == [10, 9, 6]          # a cleared cache: asked again


def test_what_the_checker_flags_is_extracted_again_and_both_looks_are_reused_on_the_next_run(tmp_path):
    a = _project(tmp_path, "t1", "p1")
    first = Recording(review_issue="column 3 is the period")
    doc = _run(a, first)
    assert "6 flagged files extracted again with the checker's issues" in {s["id"]: s["note"] for s in doc["stages"]}["check"]
    assert first.calls["A9 check"] == 2 * 2 * 6                      # two looks at each file, the second asked again
    b = _project(tmp_path, "t1", "p2")
    second = Recording(review_issue="column 3 is the period")
    _run(b, second)
    assert (second.calls["A8 extract"], second.calls["A9 check"]) == (0, 0)       # the second pass and the second look too
    assert b.reviews() == a.reviews() and len(b.reviews()) == 6


def test_a_new_version_of_one_agent_asks_only_that_agent_again(tmp_path, monkeypatch):
    """One prompt version per agent (plan 2026-11-26 §4, decision 4): a new version of the extractor's instructions makes
    the extractor read every file again, while the triage and the check of the same, unchanged extraction stay reused."""
    from modeler_agents.dataroom import stages

    _run(_project(tmp_path, "t1", "p1"), Recording())
    monkeypatch.setitem(stages.PROMPT_VERSIONS, "A8", "dataroom-7-test")
    again = Recording()
    b = _project(tmp_path, "t1", "p2")
    _run(b, again)
    assert [again.calls[s] for s in PER_FILE] == [0, again.calls["A8 extract"], 0] and again.asked("A8 extract") == 9
    assert {x["prompt"] for x in b.authors() if x["stage"] == "extract"} == {"dataroom-7-test"}
    assert {x["prompt"] for x in b.authors() if x["stage"] == "triage"} == {"dataroom-6"}


def test_every_run_stage_has_its_agent_and_only_the_extractor_moved_past_the_shared_version():
    """The split kept the one version all five agents shared, so no answer cached before it is lost; since then only
    the extractor's prompt changed (dataroom-7, phase 2b: an analyte column in a PK parameter table)."""
    from modeler_agents.dataroom import RUN_STAGES, stages

    agents = {agent for _sid, _label, agent in RUN_STAGES if agent}
    assert agents == set(stages.PROMPT_VERSIONS) == set(stages.STAGE_AGENTS.values())
    assert {stage: stages.STAGE_AGENTS[stage] for stage, _label, agent in RUN_STAGES if agent} == \
        {stage: agent for stage, _label, agent in RUN_STAGES if agent}
    assert stages.PROMPT_VERSIONS == {"A6": "dataroom-6", "A7": "dataroom-6", "A8": "dataroom-7", "A9": "dataroom-6",
                                      "A10": "dataroom-6"}


class _WithDataset(Recording):
    """The recorded delivery plus a CRO's SDTM PC dataset: its triage says it is used; nothing else is recorded for it,
    so an extractor or a checker asked about it would fail the run."""

    DATASET = "Exampleamide delivery/Clinical/pc.csv"

    def answer(self, submit: str, task: str) -> dict[str, Any]:
        path = (_FILE.search(task) or [None, ""])[1] if submit not in ("submit_question", "submit_writing") else ""
        if path == self.DATASET:
            assert submit == "submit_triage", f"{AGENTS[submit]} was asked about a dataset code described"
            return {"path": path, "purpose": "used", "topics": ["clinical_concentrations"],
                    "reason": "the CRO's SDTM PC dataset: every concentration of studies EX-02 and EX-03"}
        return super().answer(submit, task)


def test_a_dataset_code_describes_asks_no_extractor_and_no_checker(tmp_path):
    """Plan 2026-11-26 §7 phase 2b: a CDISC dataset whose standard variables say everything is described by code; the
    triage still sorts it, the extractor and the checker are not asked about it, and its author is code."""
    from modeler_project.dataroom.cdisc import DESCRIBER
    from modeler_project.dataroom.synthetic import dataset_csv, pc_dataset_rows

    store = DataRoomStore(Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    for name, data in {**delivery(), _WithDataset.DATASET: dataset_csv(pc_dataset_rows())}.items():
        store.add_upload(name, data, by="user:m")
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    model = _WithDataset()
    _run(store, model)
    assert _WithDataset.DATASET in model.files["A7 triage"]
    assert _WithDataset.DATASET not in model.files["A8 extract"] | model.files["A9 check"]
    dataset = next(f for f in store.files() if f.path == _WithDataset.DATASET)
    assert store.extraction(dataset.sha256)[1] == {"agent": "code", "describer": DESCRIBER}
    assert [(a["model"], a["identity"]) for a in store.authors() if a["file"] == _WithDataset.DATASET
            and a["stage"] == "extract"] == [("code", DESCRIBER)]
    assert model.asked("A8 extract") == len(RECORDED["extractions"]) == 9     # the delivery's own files only
