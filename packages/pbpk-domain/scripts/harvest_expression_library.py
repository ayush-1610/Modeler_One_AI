"""Harvest the expression-profile library from the OSP reference model snapshots.

PK-Sim fills an enzyme's or transporter's relative expression per organ from its expression database when a
modeller creates the profile, and the published model snapshots carry those tables explicitly. A profile built
without them has zero expression everywhere, so its metabolism or transport does nothing. This script copies the
profiles verbatim from the OSP models in ``services/engine-worker/golden/fixtures`` (the harvest rule: never
invent engine content) into ``pbpk_domain/data/expression_library.json``, one entry per molecule.

When several models carry the same molecule, the entry from a model's plain "Healthy" category is preferred (the
database defaults), otherwise the first model in alphabetical order; every other occurrence is listed under
``alternatives`` so the choice is visible. Re-run after adding a reference model:

    uv run python packages/pbpk-domain/scripts/harvest_expression_library.py [--library DIR ...]

``--library`` adds OSP model-library clones (``<drug>-model/<Drug>-Model.json``, e.g. shallow clones of
github.com/Open-Systems-Pharmacology/<Drug>-Model); each entry records the repository commit it came from. The
vendored fixtures are read first, so a molecule they carry keeps its source and the library clones add molecules
the fixtures lack (and alternatives).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "services" / "engine-worker" / "golden" / "fixtures"
OUT = REPO / "packages" / "pbpk-domain" / "src" / "pbpk_domain" / "data" / "expression_library.json"


def _commit(path: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return proc.stdout.strip() or None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, action="append", default=[])
    args = parser.parse_args()
    sources = [(p, None) for p in sorted(FIXTURES.glob("*-Model.json"))]
    fixture_models = {p.name for p, _ in sources}
    for root in args.library:
        sources += [(p, _commit(p)) for p in sorted(root.glob("*-model/*-Model.json")) if p.name not in fixture_models]

    found: dict[str, list[dict]] = {}
    for path, commit in sources:
        model = path.name.removesuffix("-Model.json")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        for profile in snapshot.get("ExpressionProfiles", []):
            found.setdefault(profile["Molecule"], []).append({"model": model, "profile": profile, "commit": commit})

    library: dict[str, dict] = {}
    for molecule, occurrences in sorted(found.items()):
        vendored = [o for o in occurrences if o["commit"] is None] or occurrences
        chosen = next((o for o in vendored if o["profile"].get("Category") == "Healthy"), vendored[0])
        profile = {k: v for k, v in chosen["profile"].items() if k != "Category"}

        def origin(o: dict) -> dict:
            return {"model": o["model"], "category": o["profile"].get("Category"), **({"commit": o["commit"]} if o["commit"] else {})}

        library[molecule] = {
            "source": origin(chosen),
            "alternatives": [origin(o) for o in occurrences if o is not chosen],
            "profile": profile,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "about": "Expression profiles harvested verbatim from the OSP reference model snapshots "
                 "(services/engine-worker/golden/fixtures, and OSP model-library clones where a source names its commit) "
                 "by scripts/harvest_expression_library.py. Do not edit by hand.",
        "molecules": library,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(library)} molecules -> {OUT.relative_to(REPO)}")
    for molecule, entry in library.items():
        print(f"  {molecule:18} {entry['profile']['Type']:12} from {entry['source']['model']} ({entry['source']['category']})")


if __name__ == "__main__":
    main()
