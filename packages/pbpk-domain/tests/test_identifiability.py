"""MS-01's fix_and_refit for a non-identifiable pair: which parameter the signed sources say to fix (PI-2b).

The owner's rule of 2026-10-25: the higher evidence grade (A–D) is the more reliable source, and measured beats
predicted. A pair they cannot rank, or rank both ways, is never guessed (UNVERIFIED for the SME).
"""

from __future__ import annotations

import pytest

from pbpk_domain.campaign.map import MapParameter
from pbpk_domain.cpf import CPF, FitPolicy, ParameterRecord, ParameterStatus, Provenance, Uncertainty
from pbpk_domain.identifiability import FixChoice, choose_fixed, fix_at_source


def _p(pid: str, value: float, status: str = "FIXED", grade: str | None = None, unit: str | None = None) -> MapParameter:
    return MapParameter(id=pid, value=value, unit=unit, status=status, source="Publication", grade=grade)


def _signed(*params: MapParameter) -> dict[str, MapParameter]:
    return {p.id: p for p in params}


@pytest.mark.req("T-14")
def test_the_higher_grade_is_fixed_at_its_signed_value_and_its_partner_refitted() -> None:
    choice = choose_fixed("phys.logp", "bind.fu", _signed(_p("phys.logp", 2.6, grade="C", unit="Log Units"),
                                                          _p("bind.fu", 0.02, grade="A")))
    assert isinstance(choice, FixChoice)
    assert (choice.fixed, choice.refit, choice.value, choice.unit, choice.status) == ("bind.fu", "phys.logp", 0.02, None, "FIXED")
    assert "a higher grade" in choice.reason and "bind.fu (grade A, measured)" in choice.reason


@pytest.mark.req("T-14")
def test_with_an_equal_grade_a_measured_value_beats_a_predicted_one() -> None:
    signed = _signed(_p("a", 1.0, "PREDICTED", "B"), _p("b", 2.0, "FIXED", "B"))
    choice = choose_fixed("a", "b", signed)
    assert isinstance(choice, FixChoice) and choice.fixed == "b" and "measured, not predicted" in choice.reason
    # with no grade on either side, the status still decides
    assert choose_fixed("a", "b", _signed(_p("a", 1.0, "PREDICTED"), _p("b", 2.0, "FIXED"))).fixed == "b"


@pytest.mark.req("T-14")
@pytest.mark.parametrize(("a", "b", "says"), [
    (_p("a", 1.0, "FIXED", "B"), _p("b", 2.0, "FIXED", "B"), "neither source is more reliable"),
    (_p("a", 1.0, "PREDICTED"), _p("b", 2.0, "PREDICTED"), "neither source is more reliable"),   # the reference refit
    (_p("a", 1.0, "FITTED"), _p("b", 2.0, "FIXED"), "neither source is more reliable"),         # FITTED is not ranked
])
def test_a_pair_the_signed_sources_cannot_rank_is_never_guessed(a, b, says) -> None:
    reason = choose_fixed("a", "b", _signed(a, b))
    assert isinstance(reason, str) and says in reason


@pytest.mark.req("T-14")
def test_where_grade_and_status_disagree_the_grade_decides() -> None:
    # the owner, 2026-10-27: a grade-A predicted value is fixed before a grade-C measured one
    choice = choose_fixed("a", "b", _signed(_p("a", 1.0, "PREDICTED", "A"), _p("b", 2.0, "FIXED", "C")))
    assert isinstance(choice, FixChoice) and (choice.fixed, choice.refit, choice.status) == ("a", "b", "PREDICTED")
    assert "a higher grade, which decides over its predicted status" in choice.reason


@pytest.mark.req("T-14")
def test_a_parameter_outside_the_signed_table_cannot_be_fixed_at_a_signed_value() -> None:
    reason = choose_fixed("Metabolite::elim.hepatic.CYP3A4.clspec", "a", _signed(_p("a", 1.0, grade="A")))
    assert isinstance(reason, str) and "not in the signed MAP's parameter table" in reason
    assert "no numeric source value" in choose_fixed(
        "a", "b", _signed(MapParameter(id="a", value="Rodgers and Rowland", unit=None, status="FIXED", source=None, grade="A"),
                          _p("b", 1.0, grade="D")))


def _fitted_cpf() -> CPF:
    return CPF(compound="Example-A", version=3, parameters=(
        ParameterRecord(id="phys.logp", value=3.4, unit="Log Units", status=ParameterStatus.FITTED, fitted_at_stage="S1",
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0),
                        provenance=Provenance(source_type="ParameterIdentification", run="c1-S1-r2"),
                        uncertainty=Uncertainty(sd=0.4, cv_percent=12.0)),
        ParameterRecord(id="bind.fu", value=0.03, status=ParameterStatus.FITTED, fitted_at_stage="S1",
                        provenance=Provenance(source_type="ParameterIdentification")),
    ))


@pytest.mark.req("T-14")
def test_the_fixed_parameter_returns_to_its_signed_value_and_status_with_no_fit_on_its_record() -> None:
    choice = choose_fixed("phys.logp", "bind.fu", _signed(_p("phys.logp", 2.6, grade="A", unit="Log Units"),
                                                          _p("bind.fu", 0.02, grade="C")))
    fixed = fix_at_source(_fitted_cpf(), choice, note="MS-01 fix_and_refit at S1 round 3")
    record = fixed.get("phys.logp")
    assert fixed.version == 4 and fixed.note == "MS-01 fix_and_refit at S1 round 3"
    assert (record.value, record.status, record.fitted_at_stage, record.uncertainty) == (2.6, ParameterStatus.FIXED, None, None)
    assert record.fit_policy is not None  # kept: the stage's later fits leave it out instead
    assert (record.provenance.source_type, record.provenance.supersedes) == ("Publication", "Example-A@3:phys.logp")
    assert fixed.get("bind.fu").value == 0.03  # the partner keeps its fitted value and is refitted


@pytest.mark.req("T-14")
def test_a_fix_in_another_unit_than_the_signed_one_is_refused() -> None:
    choice = choose_fixed("phys.logp", "bind.fu", _signed(_p("phys.logp", 2.6, grade="A", unit="log"),
                                                          _p("bind.fu", 0.02, grade="C")))
    with pytest.raises(ValueError, match="records it in 'log', the CPF in 'Log Units'"):
        fix_at_source(_fitted_cpf(), choice, note="n")
