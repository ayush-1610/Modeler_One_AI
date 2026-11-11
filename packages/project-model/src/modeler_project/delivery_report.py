"""What the agents made of a client's delivery, and how close it is to what a person reads in the files (plan
2026-11-10, R6).

The report reads a project as the server keeps it and says, per client file: how far its reading got (the reading
queue), what the delivery map says it is, what its readings proposed (datasets, study facts, dissolution rows, links),
what code refused and why, and the figures suggested for digitizing. Then, for the project: the studies with a
concentration-time profile, the dissolution profiles, the links between names, and every file not read or failed.

With an answer key (YAML, written by a person who has read the files), it scores the map and the readings: each
field of each file the key states is found, wrong or missing; each study and each dissolution condition the key
expects is found or missing; what was found and the key does not name is listed. The key is the person's reading, not a
fact: a mismatch is a question to look at, either way. Read-only: nothing is written.

    uv run python -m modeler_project.delivery_report --root ~/modeler-data/read-root --project <id> [--key key.yaml]
        [--json] [--out report.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from modeler_intake.document_reading import name_key
from modeler_project.client_data import delivery_map, document_links, submissions
from modeler_project.client_review import ALIASES
from modeler_project.client_review import record as review_record
from modeler_project.dataset_register import datasets
from modeler_project.delivery_map import FIELDS, file_line
from modeler_project.dissolution_register import profiles
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.figure_suggestions import open_suggestions
from modeler_project.reading_queue import ReadingQueue
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

TOP_REFUSALS = 8


# ---- the report ---------------------------------------------------------------------------------------------------

def _latest_items(ws: Workspace) -> dict[str, dict[str, Any]]:
    """Each file's latest reading-queue item (where its reading stands)."""
    return {i.sid: i.model_dump(mode="json") for i in ReadingQueue(ws).items()}


def _profile_studies(ws: Workspace) -> dict[str, dict[str, Any]]:
    """The studies with a concentration-time profile not rejected, by name: their datasets, points and sources."""
    out: dict[str, dict[str, Any]] = {}
    for d in datasets(ws):
        if d.state is EvidenceState.REJECTED or d.kind != "profile":
            continue
        study = str(d.study.get("study_id", ""))
        entry = out.setdefault(study, {"study": study, "datasets": 0, "points": 0, "series": 0, "sources": set(),
                                       "states": set(), "origins": set()})
        entry["datasets"] += 1
        entry["series"] += len(d.series)
        entry["points"] += sum(len(s.times) for s in d.series)
        entry["sources"].add(d.source.title if d.source else "")
        entry["states"].add(d.state.value)
        entry["origins"].add(d.origin.value if hasattr(d.origin, "value") else str(d.origin))
    for entry in out.values():
        entry["sources"], entry["states"], entry["origins"] = (sorted(x for x in entry[k] if x)
                                                              for k in ("sources", "states", "origins"))
    return out


def report(ws: Workspace) -> dict[str, Any]:
    """The delivery as the agents left it, per file and for the project (plain data, for JSON or Markdown)."""
    library = DocumentLibrary(ws)
    entries = library.entries() if library.has_record else {}
    items = _latest_items(ws)
    mapped = delivery_map(ws)
    files = []
    for sub in submissions(ws):
        sid, sha = sub["id"], sub["sha256"]
        entry = entries.get(sha)
        reads = sub.get("document_reads", [])
        last = reads[-1] if reads else {}
        sheets_read = {t.get("sheet") for m in sub.get("mappings", []) if not m.get("replaced_by")
                       for t in m.get("recipe", {}).get("tables", [])}
        item = items.get(sid)
        files.append({
            "sid": sid, "file": sub["file"], "kind": sub.get("kind", ""), "template": bool(sub.get("template")),
            "tag": entry.tag.kind if entry and entry.tag else "", "withdrawn": bool(entry and entry.withdrawn),
            "reading": {"state": item["state"], "task": item["task"], "note": item["note"], "found": item["found"],
                        "attempts": item["attempts"]} if item else None,
            "map": mapped["files"].get(sid, {}), "map_line": file_line(mapped["files"].get(sid, {})),
            "map_looked_at": sid in mapped["looked_at"], "map_tries": mapped["tries"].get(sid, 0),
            "datasets": len(sub.get("datasets", [])), "study_facts": len(sub.get("study_facts", [])),
            "dissolution_rows": len(sub.get("dissolution", [])), "links": len(sub.get("study_links", [])),
            "sheets": [t["sheet"] for t in sub.get("triage", [])],
            "sheets_read": sorted(s for s in sheets_read if s),
            "sheet_categories": {t["sheet"]: t["category"] for t in sub.get("triage", [])},
            "agent_readings": len(reads), "refused": list(last.get("refused", []))[:TOP_REFUSALS],
            "figures": len(sub.get("figure_suggestions", [])),
        })
    studies = _profile_studies(ws)
    dissolution = [{"product": p.get("key", {}).get("product", ""), "role": p.get("key", {}).get("role", ""),
                    "ph": p.get("key", {}).get("ph"), "medium": p.get("key", {}).get("medium", ""),
                    "batch": p.get("key", {}).get("batch", ""), "points": len(p.get("times_min", [])),
                    "files": p.get("files", [])} for p in profiles(ws)]
    links = [{"kind": kind, "names": link["names"], "file": link.get("file", ""), "quote": link.get("quote", "")}
             for kind in ("study", "product", "batch") for link in document_links(ws, kind)]
    return {
        "project": ws.project_id, "files": files, "studies": list(studies.values()), "dissolution": dissolution,
        "links": links, "figures": open_suggestions(ws),
        "map_runs": [{k: r.get(k) for k in ("run_id", "status", "facts", "links", "summary")} | {
            "tried": len(r.get("tried", [])), "refused": len(r.get("refused", []))} for r in mapped["runs"]],
        "counts": {
            "files": len(files),
            "read": sum(1 for f in files if f["reading"] and f["reading"]["state"] == "done"),
            "failed": sum(1 for f in files if f["reading"] and f["reading"]["state"] == "failed"),
            "waiting": sum(1 for f in files if f["reading"] and f["reading"]["state"] in ("queued", "reading")),
            "never_queued": sum(1 for f in files if not f["reading"]),
            "mapped": sum(1 for f in files if f["map_looked_at"]),
            "withdrawn": sum(1 for f in files if f["withdrawn"]),
        },
    }


# ---- the answer key and the score -----------------------------------------------------------------------------------

def load_key(path: Path) -> dict[str, Any]:
    """A person's reading of the delivery (YAML): `files` (name, and the fields each states, per sheet too),
    `studies` (each with a concentration-time profile expected, and its other names), `dissolution` (product and the
    pH of each profile expected)."""
    key = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(key, dict):
        raise TypeError("the key is a mapping with files, studies and dissolution")
    return key


def _same(field: str, expected: Any, found: Any) -> bool:
    if found is None:
        return False
    if field in ("strength_mg", "ph"):
        try:
            return abs(float(expected) - float(found)) < 1e-6
        except (TypeError, ValueError):
            return False
    if field in ("role", "food_state"):
        return str(expected).strip().lower() == str(found).strip().lower()
    return name_key(str(expected)) == name_key(str(found)) or name_key(str(expected)) in name_key(str(found))


def _names(ws: Workspace, kind: str) -> list[set[str]]:
    """Groups of names one study (or product) goes by: the aliases a person confirmed, and the links found."""
    scope = {"study": "link", "product": "plink"}[kind]
    pairs = [{name_key(a), name_key(b)} for a, b in review_record(ws).get(ALIASES[scope], {}).items()]
    pairs += [{name_key(n) for n in link["names"]} for link in document_links(ws, kind)]
    return pairs


def _known_as(name: str, groups: list[set[str]]) -> set[str]:
    keys = {name_key(name)}
    grew = True
    while grew:
        grew = False
        for group in groups:
            if group & keys and not group <= keys:
                keys |= group
                grew = True
    return keys


def score(ws: Workspace, data: dict[str, Any], key: dict[str, Any]) -> dict[str, Any]:
    """The report scored against the key: per field found / wrong / missing; studies and dissolution expected found or
    missing; what was found that the key does not name."""
    by_name = {f["file"]: f for f in data["files"]}
    fields: list[dict[str, Any]] = []
    files_missing, files_unread = [], []
    for spec in key.get("files", []):
        name = spec["name"]
        found = by_name.get(name)
        if found is None:
            files_missing.append(name)
            continue
        if not found["reading"] or found["reading"]["state"] != "done":
            files_unread.append({"file": name, "state": found["reading"]["state"] if found["reading"] else "never queued",
                                 "note": found["reading"]["note"] if found["reading"] else ""})
        targets = [(None, {k: v for k, v in spec.items() if k in FIELDS})]
        targets += [(sheet, {k: v for k, v in (fs or {}).items() if k in FIELDS}) for sheet, fs in (spec.get("sheets") or {}).items()]
        for sheet, expected in targets:
            facts = dict(found["map"].get("facts", {}))
            if sheet is not None:
                facts.update(found["map"].get("sheets", {}).get(sheet, {}).get("facts", {}))
            for field, want in expected.items():
                got = facts.get(field, {}).get("value")
                verdict = "found" if _same(field, want, got) else "missing" if got is None else "wrong"
                fields.append({"file": name, "sheet": sheet, "field": field, "expected": want, "found": got,
                               "verdict": verdict, "quote": facts.get(field, {}).get("quote", "")})
    study_groups = _names(ws, "study")
    have_studies = {name_key(s["study"]): s for s in data["studies"]}
    studies = []
    for spec in key.get("studies", []):
        keys = _known_as(spec["id"], study_groups) | {name_key(n) for n in spec.get("names", [])}
        hit = [have_studies[k] for k in keys if k in have_studies]
        studies.append({"study": spec["id"], "found": bool(hit), "as": [h["study"] for h in hit],
                        "points": sum(h["points"] for h in hit)})
    expected_keys = set()
    for spec in key.get("studies", []):
        expected_keys |= _known_as(spec["id"], study_groups) | {name_key(n) for n in spec.get("names", [])}
    unexpected = [s["study"] for s in data["studies"] if name_key(s["study"]) not in expected_keys]
    product_groups = _names(ws, "product")
    dissolution = []
    for spec in key.get("dissolution", []):
        keys = _known_as(spec["product"], product_groups) | {name_key(n) for n in spec.get("names", [])}
        for ph in spec.get("ph", [None]):
            hit = [p for p in data["dissolution"] if name_key(str(p["product"])) in keys
                   and (ph is None or (p["ph"] is not None and abs(float(p["ph"]) - float(ph)) < 1e-6))]
            dissolution.append({"product": spec["product"], "ph": ph, "found": bool(hit)})

    def share(rows: list[dict[str, Any]], ok: Any) -> str:
        return f"{sum(1 for r in rows if ok(r))}/{len(rows)}"

    return {
        "fields": fields, "files_missing": files_missing, "files_unread": files_unread, "studies": studies,
        "unexpected_studies": unexpected, "dissolution": dissolution,
        "summary": {"map_fields_found": share(fields, lambda r: r["verdict"] == "found"),
                    "map_fields_wrong": sum(1 for r in fields if r["verdict"] == "wrong"),
                    "files_read": f"{len(key.get('files', [])) - len(files_missing) - len(files_unread)}"
                                  f"/{len(key.get('files', []))}",
                    "studies_found": share(studies, lambda r: r["found"]),
                    "dissolution_found": share(dissolution, lambda r: r["found"])},
    }


# ---- Markdown -------------------------------------------------------------------------------------------------------

def _study_found(s: dict[str, Any]) -> str:
    return f"found as {', '.join(s['as'])} ({s['points']} points)" if s["found"] else "**missing**"


def _found_text(found: dict[str, int]) -> str:
    return ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in found.items() if v) or "nothing proposed"


def render(data: dict[str, Any], scored: dict[str, Any] | None = None) -> str:
    c = data["counts"]
    lines = [f"# Delivery report: project {data['project']}", "",
             (f"{c['files']} client files: {c['read']} read, {c['failed']} failed, {c['waiting']} waiting, "
              f"{c['never_queued']} never queued for the agent; {c['mapped']} mapped; {c['withdrawn']} withdrawn."), ""]
    if scored:
        s = scored["summary"]
        lines += ["## Score against the key", "",
                  f"- Map fields found: **{s['map_fields_found']}** ({s['map_fields_wrong']} wrong)",
                  f"- Files read: **{s['files_read']}**",
                  f"- Studies with a concentration-time profile: **{s['studies_found']}**",
                  f"- Dissolution profiles (product × pH): **{s['dissolution_found']}**", ""]
        wrong = [f for f in scored["fields"] if f["verdict"] != "found"]
        if wrong:
            lines += ["### Map fields not as the key says", "", "| file | sheet | field | key | found | quote |",
                      "|---|---|---|---|---|---|"]
            lines += [f"| {f['file']} | {f['sheet'] or ''} | {f['field']} | {f['expected']} | {f['found'] if f['found'] is not None else '—'}"
                      f" | {str(f['quote'])[:80]} |" for f in wrong]
            lines.append("")
        if scored["files_missing"]:
            lines += ["### Files the key names that are not in the project", ""] + [f"- {n}" for n in scored["files_missing"]] + [""]
        if scored["files_unread"]:
            lines += ["### Files not read", ""] + [f"- {f['file']}: {f['state']} {f['note']}".rstrip() for f in scored["files_unread"]] + [""]
        lines += ["### Studies", ""] + [f"- {s['study']}: {_study_found(s)}" for s in scored["studies"]]
        if scored["unexpected_studies"]:
            lines.append(f"- found, not in the key: {', '.join(scored['unexpected_studies'])}")
        lines += ["", "### Dissolution", ""] + [f"- {d['product']} pH {d['ph']}: {'found' if d['found'] else '**missing**'}"
                                                  for d in scored["dissolution"]] + [""]
    lines += ["## Each file", "", "| file | reading | found | map | refused (first) |", "|---|---|---|---|---|"]
    for f in sorted(data["files"], key=lambda f: f["file"]):
        r = f["reading"]
        state = "withdrawn" if f["withdrawn"] else (f"{r['state']}" + (f": {r['note'][:60]}" if r and r["state"] == "failed" else "")
                                                     if r else "never queued")
        found = _found_text(r["found"]) if r else ""
        if f["sheets"]:
            found += f"; sheets read {len(f['sheets_read'])}/{len(f['sheets'])}"
        lines.append(f"| {f['file']} | {state} | {found} | {f['map_line'] or ('looked at' if f['map_looked_at'] else '—')} | "
                     f"{(f['refused'][0][:80] if f['refused'] else '')} |")
    lines += ["", "## Studies with a concentration-time profile", ""]
    lines += [f"- {s['study']}: {s['datasets']} dataset(s), {s['series']} series, {s['points']} points "
              f"({', '.join(s['states'])}; from {', '.join(s['sources'])})" for s in data["studies"]] or ["- none"]
    lines += ["", "## Dissolution profiles", ""]
    lines += [f"- {d['product']} {d['role']} pH {d['ph']} {d['medium']} {d['batch']}: {d['points']} times "
              f"({', '.join(d['files'])})" for d in data["dissolution"]] or ["- none"]
    lines += ["", "## Links between names", ""]
    lines += [f"- {l['kind']}: {' = '.join(l['names'])} ({l['file']}: “{l['quote'][:80]}”)" for l in data["links"]] or ["- none"]
    lines += ["", "## Figures suggested for digitizing", ""]
    lines += [f"- {g['file']} p. {g['page']}: {g['kind']} {g['study_id'] or g['product']} (“{g['quote'][:80]}”)"
              for g in data["figures"]] or ["- none"]
    lines += ["", "## Delivery passes", ""]
    lines += [f"- {r['run_id'] or 'code'}: {r['status']}, {r['tried']} file(s), {r['facts']} facts, {r['links']} links, "
              f"{r['refused']} refused" for r in data["map_runs"]] or ["- none"]
    return "\n".join(lines) + "\n"


# ---- the command ------------------------------------------------------------------------------------------------------

def _plain(value: Any) -> Any:
    return sorted(value) if isinstance(value, set) else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="What the agents made of a client's delivery (and its score).")
    parser.add_argument("--root", required=True, help="the project store root (on the server: ~/modeler-data/read-root)")
    parser.add_argument("--project", required=True, help="the project's id (in its address: /projects/<id>/…)")
    parser.add_argument("--tenant", help="the tenant (found from the project when left out)")
    parser.add_argument("--key", help="a person's reading of the delivery (YAML), to score against")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--out", help="write the report to this file instead of printing it")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    if not args.root.strip() or not root.is_dir():
        print(f"no project store at {args.root!r}: give its folder (on the server, ~/modeler-data/read-root)", file=sys.stderr)
        return 2
    tenants = [args.tenant] if args.tenant else [t.name for t in root.iterdir() if (t / "projects" / args.project).is_dir()]
    if len(tenants) != 1:
        print(f"project {args.project} is {'in several tenants: give --tenant' if tenants else 'not in this store'}",
              file=sys.stderr)
        return 2
    ws = Workspace(FileProjectStore(root), tenants[0], args.project)
    data = report(ws)
    scored = score(ws, data, load_key(Path(args.key))) if args.key else None
    text = (json.dumps({"report": data, "score": scored}, indent=1, default=_plain, ensure_ascii=False) if args.json
            else render(data, scored))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"written to {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
