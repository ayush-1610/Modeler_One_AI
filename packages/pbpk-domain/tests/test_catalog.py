from __future__ import annotations

from pathlib import Path

import pytest

from pbpk_domain.catalog import Catalog, NoEngineBindingError

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_sample.json"


@pytest.fixture
def catalog() -> Catalog:
    return Catalog.load(FIXTURE)


def test_loads_engine_metadata(catalog: Catalog) -> None:
    assert catalog.engine.ospsuite == "12.4.4"
    assert catalog.engine.snapshot_version == 80
    assert catalog.engine.parameter_identification == "2.2.0"


def test_dimension_and_unit_lookup(catalog: Catalog) -> None:
    assert catalog.has_dimension("Molecular weight")
    assert not catalog.has_dimension("Nonexistent dimension")
    assert catalog.is_unit("Molecular weight", "g/mol")
    assert not catalog.is_unit("Molecular weight", "mg")
    assert "g/mol" in catalog.units_for("Molecular weight")


def test_is_unit_normalizes_micro_sign(catalog: Catalog) -> None:
    # µ as MICRO SIGN (U+00B5) vs GREEK SMALL LETTER MU (U+03BC) must compare equal.
    assert catalog.is_unit("Concentration (mass)", "µg/l")  # micro sign
    assert catalog.is_unit("Concentration (mass)", "μg/l")  # greek mu


def test_dimensionless_unit(catalog: Catalog) -> None:
    assert catalog.is_unit("Fraction", None)
    assert catalog.is_unit("Fraction", "")
    assert not catalog.is_unit("Molecular weight", None)


def test_units_for_unknown_dimension_raises(catalog: Catalog) -> None:
    with pytest.raises(NoEngineBindingError):
        catalog.units_for("Nope")


def test_process_type_lookup_and_parameters(catalog: Catalog) -> None:
    proc = catalog.require_process_type("MetabolizationSpecific_FirstOrder")
    assert "CLspec/[Enzyme]" in proc.parameter_names()
    assert proc.parameters[-1].unit == "l/µmol/min"
    assert "Dapagliflozin-Model" in proc.seen_in


def test_michaelis_menten_present(catalog: Catalog) -> None:
    # Real internal name harvested from the Midazolam model (not the name one might guess).
    proc = catalog.require_process_type("MetabolizationLiverMicrosomes_MM")
    assert set(proc.parameter_names()) == {"In vitro Vmax for liver microsomes", "Km", "kcat"}


def test_gfr_has_dimensionless_parameter(catalog: Catalog) -> None:
    proc = catalog.require_process_type("GlomerularFiltration")
    assert proc.parameters[0].name == "GFR fraction"
    assert proc.parameters[0].unit is None


def test_missing_process_type_raises_with_known_list(catalog: Catalog) -> None:
    with pytest.raises(NoEngineBindingError) as exc:
        catalog.require_process_type("MetabolizationSpecific_Nonsense")
    assert "MetabolizationSpecific_FirstOrder" in str(exc.value)


def test_formulation_lookup(catalog: Catalog) -> None:
    weibull = catalog.require_formulation_type("Formulation_Tablet_Weibull")
    assert "Dissolution time (50% dissolved)" in {p.name for p in weibull.parameters}
    assert catalog.formulation_type("Formulation_Nonexistent") is None


def test_pk_parameters_species_populations(catalog: Catalog) -> None:
    assert catalog.has_pk_parameter("AUC_inf")
    assert not catalog.has_pk_parameter("AUC_made_up")
    assert catalog.has_species("Human")
    assert catalog.has_population("Human", "European_ICRP_2002")
    assert not catalog.has_population("Human", "Atlantis_2099")


def test_calculation_methods(catalog: Catalog) -> None:
    assert catalog.has_calculation_method("Cellular partition coefficient method - Rodgers and Rowland", kind="compound")
    assert catalog.has_calculation_method("Body surface area - Mosteller", kind="individual")
    assert not catalog.has_calculation_method("made up", kind="compound")
    with pytest.raises(ValueError):
        catalog.has_calculation_method("x", kind="wrong")


def test_selection_pattern_confirmed(catalog: Catalog) -> None:
    assert catalog.selection_pattern_confirmed() is True


def test_selection_pattern_not_confirmed_when_a_name_diverges() -> None:
    data = Catalog.load(FIXTURE).model_dump()
    data["process_selection_naming"] = [
        *data["process_selection_naming"],
        {"internal_name": "TransportSpecific_MembraneClearance", "name": "weird custom name",
         "molecule": "OATP1B1", "data_source": "Dapa", "matches_molecule_dash_source": False, "seen_in": "X"},
    ]
    assert Catalog.from_dict(data).selection_pattern_confirmed() is False


def test_fixtures_all_roundtripped(catalog: Catalog) -> None:
    assert len(catalog.fixtures) == 4
    assert all(f.roundtrip_ok for f in catalog.fixtures)
    assert {f.name for f in catalog.fixtures} == {
        "Dapagliflozin-Model", "Midazolam-Model", "Itraconazole-Model", "Rifampicin-Model"
    }


def test_check_units_reports_bad_units(catalog: Catalog) -> None:
    problems = catalog.check_units([
        ("Molecular weight", "Molecular weight", "g/mol"),   # ok
        ("Dose", "Dose", "mg"),                               # ok
        ("Bad lipophilicity", "Lipophilicity", "mg"),         # wrong unit
    ])
    assert len(problems) == 1
    assert "Bad lipophilicity" in problems[0]


def test_unresolved_defaults_empty(catalog: Catalog) -> None:
    assert catalog.unresolved == ()
