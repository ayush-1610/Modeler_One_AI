"""The Data room's calibration run (plan 2026-11-24 §2.3; the owner's decision D2): ONE run of every Data room agent on
the made-up Exampleamide delivery (`modeler_project.dataroom.synthetic`: 10 files, software test data, never client
data, so no client permission is needed, D6), on the models of one preset, behind a hard cap. It prints what the run
cost and how many of the delivery's 60 values it got right, against the hand-written answers (`synthetic.score_room`).

On the server, after the Claude key is added and made active in Admin → Keys:

    bash deploy/server/calibrate_dataroom.sh                     # the "Claude demo" preset, capped at $5.50
    bash deploy/server/calibrate_dataroom.sh --dry               # what it would run, and the estimate; no call

Options: --preset claude-demo | claude-opus | free (the admin console's presets), --cap USD (the run's hard cap; default
5.5), --out DIR (where the report goes; default the platform folder's calibration/), --dry.

The key comes from the platform's key store (what Admin → Keys writes; MODELER_READ_ROOT and MODELER_MASTER_KEY, as the
server's scripts set them). Each paid call is priced at list prices and recorded on the platform's paid ledger, so the
month's cap (Admin → Limits) counts this run; the run stops before a call once the cap is reached (the call that
crosses it finishes). The question card is confirmed as the model drafted it, so what the model proposed is what the
rest of the run uses. Nothing is written into any project: the run's store is a temporary folder beside the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from modeler_agents.dataroom import run_room
from modeler_agents.llm import chat_model_from_env
from modeler_agents.spend import SpendBudget, guard_paid
from modeler_agents.usage_report import estimate_delivery_usd
from modeler_api import platform_settings
from modeler_project import FileProjectStore, Workspace
from modeler_project.dataroom import DataRoomStore, room_view
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import delivery, score_room, seed
from modeler_project.store import resolve_root

AGENTS = ("A6", "A7", "A8", "A9", "A10")


def _models(preset_id: str, read_root: str, master_key: str) -> dict[str, tuple[str, dict[str, str]]]:
    """Each Data room agent's (label, configuration) for the preset, with the active key of its provider."""
    preset = next((p for p in platform_settings.PRESETS if p["id"] == preset_id), None)
    if preset is None:
        sys.exit(f"no preset {preset_id!r}: one of {', '.join(p['id'] for p in platform_settings.PRESETS)}")
    keys = platform_settings.KeyStore(read_root, master_key)
    out = {}
    for agent in AGENTS:
        provider, model, effort, fallback = preset["agents"][agent]
        key = keys.active(provider)
        if key is None:
            sys.exit(f"{agent} runs on {provider}, and Admin → Keys has no active {provider} key: add one and make it active")
        setting = {"provider": provider, "model": model, "effort": effort, "fallback": fallback}
        out[agent] = (f"{provider}/{model}", platform_settings.setting_env(setting, key) | {"MODELER_LLM_TIMEOUT_S": "600"})
    return out


def _room(root: Path, fill) -> object:
    store = DataRoomStore(Workspace(FileProjectStore(root), "t1", "calibration"))
    for name, data in delivery().items():
        store.add_upload(name, data, by="user:calibration")
    if fill is not None:
        read_uploads(store, use_ocr=False, workers=1)
        fill(store)
    return store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preset", default="claude-demo")
    parser.add_argument("--cap", type=float, default=5.5)
    parser.add_argument("--out", default="")
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    read_root, master_key = os.environ.get("MODELER_READ_ROOT", ""), os.environ.get("MODELER_MASTER_KEY", "")
    if not read_root:
        sys.exit("MODELER_READ_ROOT is not set: run it through deploy/server/calibrate_dataroom.sh")

    models = _models(args.preset, read_root, master_key)
    estimate = estimate_delivery_usd({a: label.split("/", 1)[1] for a, (label, _env) in models.items()})
    caps = platform_settings.PaidCaps(read_root).current()
    ledger = platform_settings.PaidSpend(read_root)
    print(f"preset {args.preset}: " + ", ".join(f"{a} {label}" for a, (label, _e) in models.items()))
    print(f"estimate ${estimate:.2f} (a ten-file delivery); run cap ${args.cap:g}; this month's paid spend "
          f"${ledger.month_usd():.2f} of ${caps['month_usd']:g}")
    if args.dry:
        return

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else resolve_root(read_root) / platform_settings.FOLDER / "calibration" / f"{stamp}-{args.preset}"
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    run_id = f"calibration-{stamp}"

    def record(row: dict) -> None:
        rows.append(row)
        ledger.record(row | {"run_id": run_id, "tenant_id": "_platform", "project_id": "calibration"})

    budget = SpendBudget(run_cap=args.cap, month_cap=caps["month_usd"], month_spent=ledger.month_usd, record=record)
    chats = {a: guard_paid(chat_model_from_env(env), budget, platform_settings.PAID_PROVIDERS, a)
             for a, (_label, env) in models.items()}
    store = _room(out / "run", None)
    log: list[dict] = []

    def stage(names: list[str], label: str = "") -> dict:
        started = time.time()
        doc = run_room(store, chat_for=lambda agent: chats.get(agent), actor="user:calibration", stages=names,
                       use_ocr=False, workers=2, run_id=run_id)
        for s in doc["stages"]:
            if s["state"] != "skipped":
                line = {"stage": label or s["id"], "state": s["state"], "done": s["done"], "total": s["total"],
                        "seconds": round(time.time() - started, 1), "usd_so_far": round(budget.run_spent, 4),
                        "note": s["note"]}
                log.append(line)
                print(f"  {line['stage']:9s} {s['state']:8s} {s['done']}/{s['total']}  {line['seconds']:.0f} s  "
                      f"${budget.run_spent:.2f} so far", flush=True)
        if doc.get("state") == "paused":
            print(f"  PAUSED: {(doc.get('pause') or {}).get('said', '')}", flush=True)
        return doc

    began = time.time()
    stage(["read"])
    stage(["question"])
    card, _ = store.question()
    if card is not None:
        store.set_question(card, by="user:calibration", confirmed=True, reason="confirmed as drafted (calibration)")
    stage(["triage"])
    stage(["extract"])
    if store.stage_notes("extract"):
        stage(["extract"], label="extract (again, the files with no answer)")
    stage(["check"])
    stage(["write"])

    key = room_view(_room(out / "key", lambda s: seed(s, confirmed=True)))
    scored = score_room(room_view(store), key)
    counts = Counter(status for status, *_ in scored)
    by_agent: dict[str, Counter] = {}
    for row in rows:
        tally = by_agent.setdefault(f"{row['agent']} {row['model']}", Counter())
        tally.update({k: row[k] for k in ("input_tokens", "output_tokens", "cache_write", "cache_read", "usd")}, calls=1)
    report = {"preset": args.preset, "models": {a: label for a, (label, _e) in models.items()}, "estimate_usd": estimate,
              "cap_usd": args.cap, "usd": round(budget.run_spent, 4), "minutes": round((time.time() - began) / 60, 1),
              "score": {"OK": counts["OK"], "WRONG": counts["WRONG"], "MISSING": counts["MISSING"], "of": len(scored)},
              "baseline": "Nemotron Ultra's recorded run on the same delivery: 51 OK, 4 wrong, 5 missing of 60",
              "rows": [{"status": s, "what": w, "key": str(k), "got": str(g)} for s, w, k, g in scored],
              "by_agent": {k: dict(v) for k, v in by_agent.items()}, "stages": log, "calls": rows}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))

    print(f"\nCOST ${budget.run_spent:.2f} (estimate ${estimate:.2f}, cap ${args.cap:g}) over {len(rows)} paid calls, "
          f"{report['minutes']} min")
    for name, t in sorted(by_agent.items()):
        print(f"  {name:28s} {t['calls']:3d} calls  in {t['input_tokens']:>9,}  out {t['output_tokens']:>7,}  "
              f"cache read {t['cache_read']:>9,}  ${t['usd']:.2f}")
    print(f"ACCURACY {counts['OK']} of {len(scored)} right, {counts['WRONG']} wrong, {counts['MISSING']} missing "
          f"({report['baseline']})")
    for s, what, k, g in scored:
        if s != "OK":
            print(f"  {s:8s} {what}: expected {str(k)[:60]}, got {str(g)[:60]}")
    print(f"report: {out / 'report.json'}")


if __name__ == "__main__":
    main()
