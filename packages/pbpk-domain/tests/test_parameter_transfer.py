from datetime import UTC, datetime

import pytest

from pbpk_domain.snapshot.parameter_transfer import IdentifiedValue, apply_identified_values


def test_identified_values_become_simulation_overrides_with_provenance(example_snapshot):
    when = datetime(2026, 9, 15, 14, 5, tzinfo=UTC)
    updated = apply_identified_values(
        example_snapshot,
        [IdentifiedValue("IV|Example-A|Lipophilicity", 2.71, "Log Units"), IdentifiedValue("PO|Example-A|Lipophilicity", 2.71, "Log Units")],
        run_label="Fit round 2",
        when=when,
    )
    iv = next(s for s in updated.to_json_dict()["Simulations"] if s["Name"] == "IV")
    assert iv["Parameters"] == [
        {
            "Path": "Example-A|Lipophilicity",
            "Value": 2.71,
            "Unit": "Log Units",
            "ValueOrigin": {
                "Source": "ParameterIdentification",
                "Method": "ParameterIdentification",
                "Description": "Value updated from 'Fit round 2' on 2026-09-15 14:05",
            },
        }
    ]
    assert "Parameters" not in next(s for s in example_snapshot.to_json_dict()["Simulations"] if s["Name"] == "IV")
    assert updated.sha256() != example_snapshot.sha256()

    again = apply_identified_values(updated, [IdentifiedValue("IV|Example-A|Lipophilicity", 2.9)], run_label="Fit round 3", when=when)
    iv_again = next(s for s in again.simulations if s.name == "IV")
    assert [p.value for p in iv_again.parameters] == [2.9]


def test_unknown_simulation_is_rejected(example_snapshot):
    with pytest.raises(ValueError, match="no simulation named"):
        apply_identified_values(example_snapshot, [IdentifiedValue("Missing|X|Y", 1.0)], run_label="r", when=datetime(2026, 1, 1, tzinfo=UTC))
