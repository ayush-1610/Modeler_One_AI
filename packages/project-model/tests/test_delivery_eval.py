"""The evaluation set for reading a client's delivery across files (plan 2026-11-03 §3.4, I6 alongside I3): every
synthetic delivery is read with nothing missed and nothing flagged that its answer does not hold."""

from __future__ import annotations

import pytest

from modeler_project import FileProjectStore, Workspace
from modeler_project.delivery_eval import DELIVERIES, score

pytestmark = pytest.mark.req("T-47")


WORKBOOKS = [d for d in DELIVERIES if not d.needs_reader]   # the deliveries with documents are read by the agent (I4):
                                                            # services/agents/tests/test_document_reader.py


@pytest.mark.parametrize("delivery", WORKBOOKS, ids=[d.name for d in WORKBOOKS])
def test_each_delivery_is_read_as_its_answer_says(delivery, tmp_path):
    result = score(delivery, Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    assert result.perfect, f"missed {result.missed}; unexpected {result.unexpected}"
    assert result.found


def test_a_delivery_with_documents_is_not_scored_without_a_reader(tmp_path):
    delivery = next(d for d in DELIVERIES if d.needs_reader)
    with pytest.raises(ValueError, match="need a reader"):
        score(delivery, Workspace(FileProjectStore(tmp_path), "t1", "p1"))
