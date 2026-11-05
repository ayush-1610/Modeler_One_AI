"""The evaluation set for reading a client's delivery across files (plan 2026-11-03 §3.4, I6 alongside I3): every
synthetic delivery is read with nothing missed and nothing flagged that its answer does not hold."""

from __future__ import annotations

import pytest

from modeler_project import FileProjectStore, Workspace
from modeler_project.delivery_eval import DELIVERIES, score

pytestmark = pytest.mark.req("T-47")


@pytest.mark.parametrize("delivery", DELIVERIES, ids=[d.name for d in DELIVERIES])
def test_each_delivery_is_read_as_its_answer_says(delivery, tmp_path):
    result = score(delivery, Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    assert result.perfect, f"missed {result.missed}; unexpected {result.unexpected}"
    assert result.found
