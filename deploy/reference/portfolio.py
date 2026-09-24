#!/usr/bin/env python3
"""Run the whole OSP model library through Modeler One: which published drugs the tool can take, and how exactly.

    uv run python deploy/reference/portfolio.py --out reports/reference/portfolio [--roundtrip] [Drug ...]

Per drug: fetch its published snapshot (Open-Systems-Pharmacology/<Drug>-Model), import it (CPF + real clinical
studies), check S0 (completeness, placeable processes, expression profiles) and the MAP split, and, with
--roundtrip, compare every published simulation with the one the pipeline regenerates on PK-Sim (through
REFERENCE_RSCRIPT, see run_reference.py). The drugs span the complexity PBPK work meets: renal and hepatic
clearance, first-order and saturable metabolism, transporters, induction and inhibition, metabolites, tablets and
food effects, several compounds in one model. Every gap is a named row in the report, never skipped quietly.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = "https://raw.githubusercontent.com/Open-Systems-Pharmacology/{drug}-Model/{branch}/{drug}-Model.json"

# The OSP model library (github.com/Open-Systems-Pharmacology, "<Drug>-Model" repositories). A drug whose snapshot
# cannot be fetched is reported as such.
LIBRARY = (
    "Alfentanil", "Alprazolam", "Atazanavir", "Caffeine", "Carbamazepine", "Cimetidine", "Clarithromycin",
    "Dabigatran", "Dapagliflozin", "Digoxin", "Efavirenz", "Erythromycin", "Fluconazole", "Fluvoxamine",
    "Gemfibrozil", "Itraconazole", "Ketoconazole", "Levonorgestrel", "Metformin", "Midazolam", "Mirabegron",
    "Omeprazole", "Pravastatin", "Raltegravir", "Repaglinide", "Rifampicin", "Rosuvastatin", "Theophylline",
    "Trimethoprim", "Verapamil", "Voriconazole", "Warfarin",
)


def fetch(drug: str, cache: Path) -> Path | None:
    dest = cache / f"{drug}-Model.json"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    for branch in ("master", "main"):
        try:
            with urllib.request.urlopen(RAW.format(drug=drug, branch=branch), timeout=60) as response:
                body = response.read()
        except Exception as exc:  # noqa: BLE001 - any failure means "not fetched", reported per drug
            print(f"  {drug} ({branch}): {exc}", file=sys.stderr)
            continue
        if b'"Version"' in body[:2000]:
            dest.write_bytes(body)
            return dest
    return None


def assess(drug: str, path: Path) -> dict:
    from pbpk_domain.campaign.split import QuestionOfInterest, split_studies
    from pbpk_domain.cpf.build import missing_expression_profiles, unplaceable_parameters
    from pbpk_domain.cpf.completeness import check_completeness
    from pbpk_domain.reference import ReferenceImportError, import_osp_snapshot
    from pbpk_domain.reference.roundtrip import study_records

    snapshot = json.loads(path.read_text(encoding="utf-8"))
    row: dict = {"drug": drug, "compounds": [c.get("Name") for c in snapshot.get("Compounds", [])],
                 "processes": sorted({p.get("InternalName") for c in snapshot.get("Compounds", [])
                                      for p in c.get("Processes", [])}),
                 "formulations": sorted({f.get("FormulationType") for f in snapshot.get("Formulations", [])}),
                 "datasets": len(snapshot.get("ObservedData", []))}
    try:
        imported = import_osp_snapshot(snapshot)
    except ReferenceImportError as exc:
        return row | {"status": "not importable", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - an importer crash is a finding, recorded with its message
        return row | {"status": "importer error", "reason": f"{type(exc).__name__}: {exc}"}

    row |= {"studies": len(imported.studies), "linked": len(imported.simulation_of), "skipped": len(imported.skipped),
            "skip_reasons": Counter(s.split(": ", 1)[-1][:70] for s in imported.skipped).most_common(),
            "unplaced": list(imported.unplaced), "notes": list(imported.notes)}
    try:
        report = check_completeness(imported.cpf)
        unplaceable = unplaceable_parameters(imported.cpf)
        no_expression = missing_expression_profiles(imported.cpf)
    except Exception as exc:  # noqa: BLE001
        return row | {"status": "build error", "reason": f"{type(exc).__name__}: {exc}"}
    row |= {"s0_missing": list(report.missing), "unplaceable": list(unplaceable), "no_expression": list(no_expression)}
    if imported.studies:
        split = split_studies(study_records(imported), QuestionOfInterest())
        row["split"] = Counter(f"{s.study_class.value}/{s.assignment.value}" for s in split.splits).most_common()
    ready = report.ready and not unplaceable and not no_expression and not imported.unplaced and imported.studies
    row["status"] = "ready" if ready else "gaps"
    return row


def roundtrip(drug: str, path: Path, out: Path) -> dict:
    from pbpk_domain.reference import import_osp_snapshot
    from pbpk_domain.reference.roundtrip import roundtrip_inputs

    imported = import_osp_snapshot(json.loads(path.read_text(encoding="utf-8")))
    try:
        ours, pairs, notes = roundtrip_inputs(imported)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if not pairs:
        return {"error": "no study is linked to a published simulation"}
    work = out / drug
    work.mkdir(parents=True, exist_ok=True)
    (work / "ours.json").write_text(json.dumps(ours, ensure_ascii=False), encoding="utf-8")
    (work / "pairs.json").write_text(json.dumps(pairs), encoding="utf-8")
    script = REPO / "services" / "engine-worker" / "golden" / "reference_compare.R"
    cmd = [*shlex.split(os.environ.get("REFERENCE_RSCRIPT", "Rscript")), str(script), str(path),
           str(work / "ours.json"), str(work / "pairs.json"), str(work / "engine")]
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    report_path = work / "engine" / "roundtrip.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return {"seconds": round(time.monotonic() - started), "identical": report.get("identical"),
            "total": report.get("total"), "pairs": report.get("pairs", []), "notes": notes,
            "stderr_tail": "" if report else proc.stderr[-3000:]}


def markdown(rows: list[dict]) -> str:
    lines = ["| drug | status | studies (linked) | skipped | processes | round trip | gaps |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        rt = r.get("roundtrip") or {}
        rt_text = (f"{rt.get('identical')}/{rt.get('total')} identical" if "total" in rt and rt.get("total")
                   else (rt.get("error", "") if rt else ""))
        gaps = "; ".join([*r.get("unplaced", []), *(f"S0: {m}" for m in r.get("s0_missing", [])),
                          *(f"no placement: {u}" for u in r.get("unplaceable", [])),
                          *(f"no expression: {m}" for m in r.get("no_expression", [])),
                          *([r["reason"]] if r.get("reason") else [])])[:400]
        lines.append(f"| {r['drug']} | {r['status']} | {r.get('studies', '')} ({r.get('linked', '')}) | "
                     f"{r.get('skipped', '')} | {', '.join(p for p in r.get('processes', []) if p)[:120]} | "
                     f"{rt_text} | {gaps} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("drugs", nargs="*", default=list(LIBRARY))
    parser.add_argument("--out", type=Path, default=REPO / "reports" / "reference" / "portfolio")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--roundtrip", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.cache or (args.out / "snapshots")
    cache.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for drug in args.drugs:
        path = fetch(drug, cache)
        if path is None:
            rows.append({"drug": drug, "status": "not fetched", "reason": "no snapshot at the OSP library URL"})
            continue
        row = assess(drug, path)
        if args.roundtrip and row["status"] in ("ready", "gaps") and row.get("linked"):
            row["roundtrip"] = roundtrip(drug, path, args.out)
        rows.append(row)
        print(f"{drug}: {row['status']}", flush=True)
    (args.out / "portfolio.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str),
                                             encoding="utf-8")
    text = "### OSP library through Modeler One\n" + markdown(rows)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(text + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
