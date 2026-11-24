"""What a Data room run is expected to cost on a paid model, said before it starts (plan 2026-11-24 §2.4, guard 3).

An estimate, from what our stored runs measured (§2.2: three made-up deliveries of 8 to 11 files, a full run A6 to A10,
counted by Nemotron's tokenizer: 84 to 102 model calls, 0.51 to 1.13 M input and 93 to 131 k output tokens). Per file
the agents still have to read:
- **calls:** 8.5 to 10 (85 to 100 for a 10-file delivery);
- **input:** each call sends the agent's instructions and tools (about `PROMPT_TOKENS`) and, on average, half of the
  file's text read so far: `calls × (PROMPT_TOKENS + T / 2)`, where T is the file's text in tokens, its characters / 4,
  at most `READ_CAP_TOKENS` (an agent reads a large file through its tools, a page at a time, never whole). For files of
  15,000 to 56,000 characters this gives the measured 50 k to 110 k tokens a file;
- **output:** 9,000 to 13,000 tokens, × 1.5 because Claude's thinking counts as output (§2.2's assumption).

A file not read yet counts its bytes as its characters (an overestimate for a PDF or a workbook, bounded by the cap). A
file already extracted, or sorted as not needed, is not read again (a re-run, a resumed run) and costs nothing.

The work is shared between the agents (our estimate, not measured): A6 the question 5 %, A7 sorting 15 %, A8
extraction 60 %, A9 checking 15 %, A10 writing 5 %. Each agent's share is priced at its own model's list price
(`usage_report.PRICES`, the prices of the usage page; a model it does not price as the dearest), without the cache: the
run is cached at every turn, so it usually costs less. A free model's share costs nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from typing import Any

from modeler_agents.usage_report import DEAREST, PRICES, price_key
from modeler_project.dataroom.store import DataRoomStore

CALLS_PER_FILE = (8.5, 10.0)
PROMPT_TOKENS = 4_000
READ_CAP_TOKENS = 20_000
OUTPUT_PER_FILE = (9_000, 13_000)
THINKING = 1.5
CHARS_PER_TOKEN = 4
SHARES = {"A6": 0.05, "A7": 0.15, "A8": 0.60, "A9": 0.15, "A10": 0.05}


def files_to_do(store: DataRoomStore) -> list[tuple[str, int]]:
    """Each file the agents still have to read, with its text's characters (a file not read yet: its bytes)."""
    from modeler_intake.room import document_text, expand_uploads

    read = {f.sha256: f for f in store.files()}
    expanded, _unreadable = expand_uploads([(u["name"], store.upload_bytes(u["sha256"])) for u in store.uploads()])
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for path, data in expanded:
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen:
            continue
        seen.add(sha)
        f = read.get(sha)
        if f is None:
            out.append((path, len(data)))
            continue
        if f.duplicate_of or f.same_content_as or f.state not in ("read", "partly_read"):
            continue
        if store.extraction(sha) is not None or (f.triage is not None and f.triage.purpose != "used"):
            continue
        doc = store.doc(sha)
        chars = sum(len(line) for _part, lines in document_text(doc) for line in lines) if doc is not None else len(data)
        out.append((f.path, chars))
    return out


def estimate(files: list[tuple[str, int]], models: Mapping[str, tuple[str, str]], paid: Collection[str]) -> dict[str, Any]:
    """The run's estimate: `files` as `files_to_do` gives them, `models` each agent's (provider, model id) it starts on,
    `paid` the providers that cost money. Dollars only for the agents on a paid model."""
    per_file = [min(chars / CHARS_PER_TOKEN, READ_CAP_TOKENS) for _path, chars in files]
    calls = tuple(round(c * len(files)) for c in CALLS_PER_FILE)
    inputs = tuple(round(sum(c * (PROMPT_TOKENS + t / 2) for t in per_file)) for c in CALLS_PER_FILE)
    outputs = tuple(o * len(files) for o in OUTPUT_PER_FILE)
    usd = [0.0, 0.0]
    agents = []
    for agent, share in SHARES.items():
        provider, model = models.get(agent, ("", ""))
        costs = provider in paid
        agents.append({"agent": agent, "provider": provider, "model": model, "paid": costs})
        if not costs:
            continue
        p_in, _write, _read, p_out = PRICES[price_key(model) or DEAREST]
        for i in (0, 1):
            usd[i] += share * (inputs[i] * p_in + outputs[i] * THINKING * p_out) / 1e6
    low, high = (round(u, 2) for u in usd)
    return {"paid": any(a["paid"] for a in agents), "files": len(files), "characters": sum(c for _p, c in files),
            "calls_low": calls[0], "calls_high": calls[1], "input_tokens_low": inputs[0], "input_tokens_high": inputs[1],
            "output_tokens_low": outputs[0], "output_tokens_high": outputs[1], "usd_low": low, "usd_high": high,
            "usd": round((low + high) / 2, 2), "agents": agents,
            "basis": ("tokens ≈ characters / 4 of each file's text; per file 8.5 to 10 model calls, each sending the "
                      "instructions (about 4,000 tokens) and half the file's text read so far, and 9,000 to 13,000 "
                      "output tokens × 1.5 for thinking (measured on three 8 to 11-file deliveries, plan 2026-11-24 "
                      "§2.2); each agent's share at its model's list price, without the cache")}
