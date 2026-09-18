"""Repository-wide pytest configuration: the requirement trace matrix (task T-25).

Tests declare the requirement they verify with ``@pytest.mark.req("F-403")`` (or several ids). Running with
``--trace-matrix reports/trace-matrix.md`` writes a matrix mapping every declared requirement id to the tests
that cover it (Markdown plus a JSON sibling), which CI uploads as the validation-evidence artifact. The marker
is inert without the flag, so a normal test run is unaffected.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption(
        "--trace-matrix", action="store", default=None, metavar="PATH",
        help="write the requirement->test trace matrix to PATH (Markdown; a .json sibling is written too)",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "req(id, ...): requirement/feature id(s) this test verifies (T-25 trace matrix)")


def pytest_sessionfinish(session, exitstatus):
    out = session.config.getoption("trace_matrix")
    if not out:
        return
    matrix: dict[str, list[str]] = defaultdict(list)
    for item in session.items:
        for marker in item.iter_markers(name="req"):
            for req_id in marker.args:
                matrix[str(req_id)].append(item.nodeid)

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {rid: sorted(set(tests)) for rid, tests in sorted(matrix.items())}

    lines = ["# Requirement trace matrix", "", f"{len(ordered)} requirement(s) covered by {sum(len(t) for t in ordered.values())} test(s).", ""]
    for rid, tests in ordered.items():
        lines.append(f"## {rid} ({len(tests)})")
        lines.extend(f"- `{t}`" for t in tests)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps(ordered, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\ntrace matrix: {len(ordered)} requirement(s) -> {path}")
