"""File-backed agent runs for the single-node deployment (the `RunStore` protocol of `modeler_agents.run`).

Layout ``<root>/<tenant>/agent_runs/<run_id>/run.json`` (the run, rewritten on finish) and ``steps.jsonl`` (one
immutable line per step). The Postgres `agent_runs` / `agent_steps` tables implement the same protocol (T-20).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


class FileRunStore:
    def __init__(self, root: str | Path, *, project_id: str | None = None):
        self.root = Path(root)
        self.project_id = project_id

    def _dir(self, tenant_id: str, run_id: str) -> Path:
        return self.root / tenant_id / "agent_runs" / run_id

    def _tenant_of(self, run_id: str) -> str:
        for path in self.root.glob(f"*/agent_runs/{run_id}/run.json"):
            return path.parts[-4]
        raise KeyError(run_id)

    def start_run(self, *, tenant_id: str, agent: str, provider: str, model: str, campaign_id: str | None,
                  budget: dict[str, Any]) -> str:
        run_id = f"ar_{uuid.uuid4().hex[:12]}"
        folder = self._dir(tenant_id, run_id)
        folder.mkdir(parents=True, exist_ok=True)
        record = {"run_id": run_id, "tenant_id": tenant_id, "project_id": self.project_id, "agent": agent,
                  "provider": provider, "model": model, "campaign_id": campaign_id, "budget": budget,
                  "status": "RUNNING", "started_at": datetime.now(UTC).isoformat(), "finished_at": None,
                  "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "summary": {}, "proposals": []}
        (folder / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return run_id

    def record_step(self, *, run_id: str, seq: int, kind: str, content: dict[str, Any], usage: dict[str, int]) -> None:
        folder = self._dir(self._tenant_of(run_id), run_id)
        line = json.dumps({"seq": seq, "kind": kind, "at": datetime.now(UTC).isoformat(), "content": content,
                           "usage": usage}, ensure_ascii=False, default=str)
        with _LOCK, (folder / "steps.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def record_proposal(self, *, run_id: str, parameter_id: str, value: str | None, unit: str | None,
                        citation: dict[str, Any]) -> str:
        record = self.get(run_id)
        proposal_id = f"{run_id}-p{len(record['proposals']) + 1}"
        record["proposals"].append({"proposal_id": proposal_id, "parameter_id": parameter_id, "value": value,
                                    "unit": unit, "citation": citation})
        self._write(record)
        return proposal_id

    def finish_run(self, *, run_id: str, status: str, input_tokens: int, output_tokens: int, cost_usd: float,
                   summary: dict[str, Any]) -> None:
        record = self.get(run_id)
        record.update(status=status, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
                      summary=summary, finished_at=datetime.now(UTC).isoformat())
        self._write(record)

    def _write(self, record: dict[str, Any]) -> None:
        path = self._dir(record["tenant_id"], record["run_id"]) / "run.json"
        with _LOCK:
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # --- reads ----------------------------------------------------------------------------------------------

    def get(self, run_id: str) -> dict[str, Any]:
        path = self._dir(self._tenant_of(run_id), run_id) / "run.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def steps(self, run_id: str) -> list[dict[str, Any]]:
        path = self._dir(self._tenant_of(run_id), run_id) / "steps.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def runs(self, tenant_id: str, *, project_id: str | None = None, agent: str | None = None) -> list[dict[str, Any]]:
        base = self.root / tenant_id / "agent_runs"
        if not base.exists():
            return []
        out = []
        for path in base.glob("*/run.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if (project_id is None or record.get("project_id") == project_id) and (agent is None or record["agent"] == agent):
                out.append(record)
        return sorted(out, key=lambda r: r["started_at"], reverse=True)
