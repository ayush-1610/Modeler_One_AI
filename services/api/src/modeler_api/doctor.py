"""Project doctor: one project's state as a report a person can read and share, run on the server.

    source deploy/server/_env.sh                       # MODELER_READ_ROOT and the logs directory
    uv run python -m modeler_api.doctor --list         # the projects (tenant, id, drug, phases)
    uv run python -m modeler_api.doctor <project_id>   # the report, also written to $MODELER_LOGS/doctor-<id>.md

For each phase it says where the project stands and what stops it: the brief and data plan, the client files (sheets
read or not, the reconciliation), the evidence register (accepted values per parameter, conflicts, names the model does
not use), the datasets (metadata only), the CPF and the P4 readiness with its to-do list, the last audit events and the
API log's recent errors. It never prints observed concentrations or dissolution values, keys or passwords; the client's
file and study names do appear, so share the report only with people who may see the project.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from modeler_api.config import get_settings
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.evidence import EvidenceState

_ERROR = re.compile(r"Traceback|ERROR|Exception|\b5\d\d\b")


def _store() -> FileProjectStore:
    root = get_settings().read_root
    if not root:
        raise SystemExit("MODELER_READ_ROOT is not set: run `source deploy/server/_env.sh` first")
    return FileProjectStore(root)


def projects(store: FileProjectStore) -> list[tuple[str, str]]:
    return sorted((t.name, p.name) for t in store.root.iterdir() if (t / "projects").is_dir() for p in (t / "projects").iterdir()
                  if p.is_dir())


def _brief(ws: Workspace) -> ProjectBrief | None:
    version = ws.latest(ArtifactKind.BRIEF, "main")
    return ProjectBrief.from_content(version.content) if version else None


def _status(ws: Workspace, kind: ArtifactKind, artifact_id: str) -> str:
    version = ws.latest(kind, artifact_id)
    return f"v{version.version} {ws.status(version).value.lower()}" if version else "not started"


def report(ws: Workspace, *, logs: Path | None = None) -> str:
    """The project's state in Markdown (no observed values, no secrets)."""
    from modeler_project.client_data import reconcile, submissions
    from modeler_project.dataset_register import datasets
    from modeler_project.evidence import review_flags
    from modeler_project.evidence_register import items
    from modeler_project.inputs import dataset_warnings, placement, todo
    from modeler_project.requirements import RequirementMatrix

    out: list[str] = []
    w = out.append
    brief = _brief(ws)
    w(f"# Project doctor · {ws.project_id} (tenant {ws.tenant_id})\n")
    w("## Phases\n")
    w(" · ".join(f"{p} {s.value.lower()}" for p, s in ws.phases().items()) + "\n")

    w("## P1 brief and data plan\n")
    if brief is None:
        w("- no brief\n")
    else:
        w(f"- drug: **{brief.drug_name}** · PubChem CID {brief.value('drug.pubchem_cid') or '—'} · MW (free base) "
          f"{brief.value('drug.mw_free_base') or '—'}")
        w(f"- applications: {', '.join(map(str, brief.value('qoi.applications') or [])) or '—'}")
        products = [f"{brief.value(f'products[{i}].name')} ({brief.value(f'products[{i}].role')})"
                    for i in range(len(brief.groups.get("products", ())))]
        w(f"- products: {', '.join(products) or '—'}")
        w(f"- brief {_status(ws, ArtifactKind.BRIEF, 'main')} · data plan {_status(ws, ArtifactKind.REQUIREMENTS, 'main')}\n")
    matrix_version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    matrix = RequirementMatrix.from_content(matrix_version.content) if matrix_version else None

    w("## P3 client data\n")
    subs = submissions(ws)
    for sub in subs:
        read = {t.get("sheet") for m in sub.get("mappings", []) for t in m["recipe"].get("tables", [])}
        sheets = [f"{t['sheet']} [{t['category'].lower()}{', read' if t['sheet'] in read else ''}]" for t in sub.get("triage", [])]
        w(f"- {sub['file']} ({'template' if sub.get('template') else sub.get('kind')}): {len(sub.get('datasets', []))} datasets"
          + (f"; sheets: {'; '.join(sheets)}" if sheets else ""))
    if not subs:
        w("- no client files")
    if matrix is not None:
        recon = reconcile(ws, matrix)
        for r in recon.rows:
            w(f"  - {r.req_id}: {r.status.lower()}{' (blocks P3)' if r in recon.blocking() else ''}"
              f"{f' — {r.detail}' if r.detail else ''}")
    w(f"- register {_status(ws, ArtifactKind.CLIENT_SUBMISSION, 'register')}\n")

    w("## P2 evidence register\n")
    evidence = items(ws)
    w(f"- {len(evidence)} items: " + ", ".join(f"{n} {s.lower()}" for s, n in Counter(e.state.value for e in evidence).items()))
    accepted: dict[str, list] = defaultdict(list)
    for e in evidence:
        if e.state is EvidenceState.ACCEPTED:
            accepted[e.target].append(e)
    for target, values in sorted(accepted.items()):
        where = placement(target) if target not in ("phys.pka",) else "model"
        note = " ⚠ several accepted (keep one)" if len(values) > 1 and target != "phys.pka" else ""
        note += " ⚠ not a parameter the model uses" if where is None and "{" not in target else ""
        note += " ⚠ template target" if "{" in target or "<" in target else ""
        shown = ", ".join(f"{e.value}{' ' + e.unit if e.unit else ''} [{e.id}, grade {e.confidence}, {e.source.title[:40] or e.source_type.value.lower()}]"
                          for e in values[:6])
        w(f"- `{target}`: {shown}{note}")
        for check in sorted({f for e in values for f in review_flags(e)}):
            w(f"  - {check}")
    w("")

    w("## Datasets (metadata only)\n")
    for d in datasets(ws):
        stats = sorted({s.statistic for s in d.series})
        w(f"- {d.study.get('study_id')} · {d.state.value.lower()} · {d.purpose} · {d.origin.value.lower()} · {d.kind} · "
          f"{len(d.series)} series ({', '.join(stats)}) · {d.study.get('route')} {d.study.get('dose_mg')} mg "
          f"{d.study.get('formulation')} {d.study.get('food_state')} · n {d.study.get('n')}")
    if not datasets(ws):
        w("- none")
    for warning in dataset_warnings([d for d in datasets(ws) if d.state is not EvidenceState.REJECTED]):
        w(f"- ⚠ {warning}")
    w("")

    w("## P4 model inputs\n")
    cpf = ws.latest(ArtifactKind.CPF, "main")
    ready = ws.latest(ArtifactKind.READINESS, "main")
    if cpf is None:
        w("- not assembled")
    else:
        records = cpf.content["cpf"]["parameters"]
        w(f"- CPF v{cpf.version}: {len(records)} parameters: " + ", ".join(r["id"] for r in records))
    if ready is not None:
        w(f"- readiness v{ready.version}: {'ready' if ready.content['ready'] else 'NOT ready'}")
        for c in ready.content["checks"]:
            w(f"  - [{'ok' if c['ok'] else 'open'}] {c['check']}" + "".join(f"\n    - {d}" for d in c["detail"]))
        w("- to do: " + ("; ".join(f"{t['kind']} {t['target']}" for t in todo(ws)) or "nothing"))
    w("")

    w("## Last audit events\n")
    events = [r.event for r in ws.store.audit(ws.tenant_id).records() if r.event.resource_id.startswith(ws.project_id)]
    for e in events[-25:]:
        w(f"- {e.occurred_at[:19]} {e.actor} {e.action} {e.resource_type} {e.resource_id.split('/', 1)[-1]}"
          f"{f' — {e.reason[:120]}' if e.reason else ''}")
    w("")

    if logs is not None:
        log = logs / "api.log"
        w("## API log: recent errors\n")
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]
            hits = [line for line in lines if _ERROR.search(line) and "Authorization" not in line]
            w("```\n" + "\n".join(hits[-40:] or ["(none in the last 4000 lines)"]) + "\n```")
        else:
            w(f"- no {log}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project", nargs="?", help="the project id (see --list)")
    parser.add_argument("--tenant", help="the tenant (default: the only one holding the project)")
    parser.add_argument("--list", action="store_true", help="list the projects")
    args = parser.parse_args(argv)
    store = _store()
    found = projects(store)
    if args.list or not args.project:
        for tenant, pid in found:
            ws = Workspace(store, tenant, pid)
            brief = _brief(ws)
            phases = " ".join(f"{p}:{s.value.lower()}" for p, s in ws.phases().items())
            print(f"{tenant}\t{pid}\t{brief.drug_name if brief else '—'}\t{phases}")
        return 0
    tenants = [t for t, p in found if p == args.project and (args.tenant is None or t == args.tenant)]
    if len(tenants) != 1:
        print(f"project {args.project!r}: {'not found' if not tenants else 'in several tenants, give --tenant'}", file=sys.stderr)
        return 1
    logs = Path(get_settings().logs or Path.home() / "modeler-logs")
    text = report(Workspace(store, tenants[0], args.project), logs=logs)
    print(text)
    if logs.is_dir():
        path = logs / f"doctor-{args.project}.md"
        path.write_text(text, encoding="utf-8")
        print(f"(written to {path})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
