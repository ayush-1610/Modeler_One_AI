"""Harvest the expression-profile library from the OSP reference model snapshots.

PK-Sim fills an enzyme's or transporter's relative expression per organ from its expression database when a
modeller creates the profile, and the published model snapshots carry those tables explicitly. A profile built
without them has zero expression everywhere, so its metabolism or transport does nothing. This script copies the
profiles verbatim from the OSP models in ``services/engine-worker/golden/fixtures`` (the harvest rule: never
invent engine content) into ``pbpk_domain/data/expression_library.json``, one entry per molecule.

When several models carry the same molecule, the entry from a model's plain "Healthy" category is preferred (the
database defaults), otherwise the first model in alphabetical order; every other occurrence is listed under
``alternatives`` so the choice is visible. Re-run after adding a reference model:

    uv run python packages/pbpk-domain/scripts/harvest_expression_library.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "services" / "engine-worker" / "golden" / "fixtures"
OUT = REPO / "packages" / "pbpk-domain" / "src" / "pbpk_domain" / "data" / "expression_library.json"


def main() -> None:
    found: dict[str, list[dict]] = {}
    for path in sorted(FIXTURES.glob("*-Model.json")):
        model = path.name.removesuffix("-Model.json")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        for profile in snapshot.get("ExpressionProfiles", []):
            found.setdefault(profile["Molecule"], []).append({"model": model, "profile": profile})

    library: dict[str, dict] = {}
    for molecule, occurrences in sorted(found.items()):
        chosen = next((o for o in occurrences if o["profile"].get("Category") == "Healthy"), occurrences[0])
        profile = {k: v for k, v in chosen["profile"].items() if k != "Category"}
        library[molecule] = {
            "source": {"model": chosen["model"], "category": chosen["profile"].get("Category")},
            "alternatives": [
                {"model": o["model"], "category": o["profile"].get("Category")} for o in occurrences if o is not chosen
            ],
            "profile": profile,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "about": "Expression profiles harvested verbatim from the OSP reference model snapshots "
                 "(services/engine-worker/golden/fixtures) by scripts/harvest_expression_library.py. Do not edit by hand.",
        "molecules": library,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(library)} molecules -> {OUT.relative_to(REPO)}")
    for molecule, entry in library.items():
        print(f"  {molecule:18} {entry['profile']['Type']:12} from {entry['source']['model']} ({entry['source']['category']})")


if __name__ == "__main__":
    main()
