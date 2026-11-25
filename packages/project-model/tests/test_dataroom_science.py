"""The Data room's science checks (plan 2026-11-24 §8, features 3–9), each on a small synthetic table: the client's
NCA reproduced with its method found, exclusions flagged and never deleted, observed data that know their statistic,
the permeability guard, dissolution checks, which step limits absorption, and excipients by function. The thresholds
are `dataroom_rules.yaml` 0.3's, UNVERIFIED (the literature's proposal, awaiting the SME); no client data."""

from __future__ import annotations

import math

import pytest

from modeler_intake.room import read_file
from modeler_intake.room_specs import ColumnSpec, Extraction, Fact, ProductRef, QuestionCard, TableDescription
from modeler_intake.source import parse_document
from modeler_project.dataroom.assemble import Inputs, assemble
from modeler_project.dataroom.clinical import samples_from, study_view
from modeler_project.dataroom.extract import read_table
from modeler_project.dataroom.model import CheckedFact, Chip, DissolutionView, FileView, SolubilityRow
from modeler_project.dataroom.rules import load_rules
from pbpk_domain.nca import nca

pytestmark = pytest.mark.req("T-47")


def c(i: int, role: str, **kw) -> ColumnSpec:
    return ColumnSpec(index=i, role=role, **kw)


def table(name: str, text: str, desc: TableDescription):
    f = read_file(name, text.encode())
    return read_table(desc.model_copy(update={"file": name}), f.document, file=name, sha256=f.sha256)


def _room(files: dict[str, str], extractions: list[Extraction], question: QuestionCard | None = None):
    views, docs = [], {}
    for name, text in files.items():
        doc = parse_document(text.encode(), name)
        views.append(FileView(path=f"D/{name}", name=name, sha256=doc.file_sha256, kind="delimited"))
        docs[doc.file_sha256] = doc
    return assemble(Inputs(files=views, docs=docs, question=question, question_confirmed=True, extractions=extractions))


def _said(field: str, value: str, quote: str, subject: str = "S") -> CheckedFact:
    return CheckedFact(fact=Fact(field=field, subject=subject, value=value, quote=quote), ok=True,
                       chip=Chip(file="notes.md", part="body", line=1, text=quote))


def test_the_rules_carry_the_new_checks_unverified_at_0_3():
    rules = load_rules()
    assert (rules.version, rules.status) == ("0.3", "UNVERIFIED")
    rep = rules.nca.reproduce
    assert (rep.pass_percent, rep.investigate_percent) == (1.0, 5.0)
    assert rep.integration[0] == "linear-up/log-down" and rep.lambda_z[0] == "best_fit"     # ours first
    assert (rules.flags.predose_max_percent_of_cmax, rules.flags.auc_extrapolated_max_percent) == (5, 20)
    assert rules.reference_compound("Metoprolol tartrate (high permeability marker)") == "metoprolol"
    found = rules.excipient_class("Hypromellose acetate succinate (HPMCAS-MF)")
    assert found is not None and (found[0].id, found[1]) == ("polymer", "name")     # the longest name first


# --- feature 3: the client's NCA reproduced, its method found -------------------------------------------------------

TIMES = (0, 0.5, 1, 2, 4, 6, 8, 12, 24)


def _conc(t: float, s: int) -> float:
    ka, ke = 1.6 + 0.1 * s, 0.17 + 0.01 * s
    return round(100 * ka / (ka - ke) * (math.exp(-ke * t) - math.exp(-ka * t)), 3)


def test_the_clients_nca_method_is_found_and_each_value_put_in_its_tier():
    """The client used the linear trapezoidal rule at the actual sampling times. Code finds both settings, reproduces
    every value but two, and tiers those: subject 3's AUC +3 % is to investigate (a setting differs), subject 4's Cmax
    +8 % differs under every setting tried (the data differ: ask)."""
    actual = {0.5: 0.6, 1: 1.1, 2: 2.0, 4: 4.05}                     # the late samples on time
    lines, client = ["Subject,Time,Actual,Conc"], ["Subject,Cmax,Tmax,AUClast,AUCinf,T1/2"]
    for s in (1, 2, 3, 4):
        ts, cs = [], []
        for t in TIMES:
            a = actual.get(t, t)
            value = 0.0 if t == 0 else _conc(a, s)
            lines.append(f"{s},{t},{a},{'BLQ' if t == 0 else value}")
            ts.append(a)
            cs.append(value)
        res = nca(ts, cs, integration="linear")
        auc = res.auc_last * (1.03 if s == 3 else 1.0)
        cmax = res.c_max * (1.08 if s == 4 else 1.0)
        client.append(f"{s},{cmax:.5g},{res.t_max:g},{auc:.6g},{res.auc_inf:.6g},{res.t_half:.5g}")
    dc = TableDescription(file="", kind="concentrations", part="sheet:c", header_lines=[1], first_line=2,
                          last_line=len(lines), time_unit="h", value_unit="ng/mL",
                          columns=[c(1, "subject"), c(2, "time"), c(3, "actual_time"), c(4, "value")])
    dp = TableDescription(file="", kind="pk_parameters", part="sheet:p", header_lines=[1], first_line=2, last_line=5,
                          value_unit="ng/mL", columns=[c(1, "subject"), c(2, "cmax"), c(3, "tmax"), c(4, "auc_t"),
                                                       c(5, "auc_inf"), c(6, "t_half")])
    sv = study_view("S", concentrations=[table("c.csv", "\n".join(lines) + "\n", dc)],
                    pk_tables=[table("p.csv", "\n".join(client) + "\n", dp)])
    rep = sv.nca_reproduction
    assert rep is not None and sv.nca_method_client == "linear trapezoidal"
    assert (rep.settings.integration, rep.settings.time_basis) == ("linear trapezoidal", "actual times")
    assert {"integration", "time_basis"} <= set(rep.told_apart)
    assert (rep.investigate, rep.differ) == (1, 1) and rep.compared == 20
    assert rep.explained > 0                                  # reproduced only with the client's settings
    tiers = {r.subject: r.tiers for r in sv.nca}
    assert tiers["3"]["auc_t"] == "investigate" and tiers["4"]["cmax"] == "differ"
    assert all(t in ("pass", "explained") for s, got in tiers.items() for role, t in got.items()
               if (s, role) not in (("3", "auc_t"), ("4", "cmax")))
    off = sorted(p.message for p in sv.problems if p.code == "NCA_DIFFERS")
    assert [m.split(":")[0] for m in off] == ["subject 3", "subject 4"]
    assert "AUC0–t" in off[0] and "investigate" in off[0]
    assert "Cmax" in off[1] and "the data differ, ask the client" in off[1]
    method = next(p.message for p in sv.problems if p.code == "CLIENT_NCA_METHOD")
    assert method.startswith("the client's NCA is reproduced with: linear trapezoidal; actual times")
    assert "UNVERIFIED" in rep.tiers


def test_a_setting_the_clients_values_do_not_depend_on_is_said_not_claimed():
    conc = "Subject,Period,Treatment,0,1,2,4,8,12\n" + "".join(f"{s},1,A,0,10,8,5,2.5,1.25\n" for s in (1, 2))
    d = TableDescription(file="", kind="concentrations", part="sheet:c", header_lines=[1], first_line=2, last_line=3,
                         time_unit="h", value_unit="ng/mL", zero_means_blq=True,
                         columns=[c(1, "subject"), c(2, "period"), c(3, "treatment")] + [c(4 + i, "value", time=float(x))
                                                                                         for i, x in enumerate((0, 1, 2, 4, 8, 12))])
    pk = "Subject,Period,Cmax\n1,1,10\n2,1,10\n"
    dp = TableDescription(file="", kind="pk_parameters", part="sheet:p", header_lines=[1], first_line=2, last_line=3,
                          value_unit="ng/mL", columns=[c(1, "subject"), c(2, "period"), c(3, "cmax")])
    sv = study_view("S", concentrations=[table("c.csv", conc, d)], pk_tables=[table("p.csv", pk, dp)])
    rep = sv.nca_reproduction
    assert rep is not None and rep.told_apart == () and rep.passed == 2
    assert rep.not_told["time_basis"] == "the data give no actual sampling times"
    assert rep.not_told["integration"] == "no value the client gives depends on it"
    assert sv.nca_method_client == ""                         # no client AUC: no integration rule claimed


# --- feature 4: exclusions flagged, never deleted -------------------------------------------------------------------

def test_exclusions_are_flagged_with_their_reasons_and_every_subject_stays_in_its_sets():
    times = (0, 0.5, 1, 2, 4, 8, 12)
    rows = {1: (1.2, 6, 10, 8, 5, 2.5, 1.25),                 # pre-dose 12 % of Cmax
            2: (0, 6, 10, 9.5, 9, 8.5, 8),                    # still high at 12 h: AUC mostly extrapolated, short span
            3: (0, 6, 10, 8, 5, 2.5, 1.25),
            4: (0, 6, 10, 8, 5, 2.5, 1.25)}
    conc = "Subject,Time,Actual,Conc\n" + "".join(
        f"{s},{t},{t + (0.5 if (s, t) == (3, 2) else 0)},{v}\n" for s, vs in rows.items() for t, v in zip(times, vs, strict=True))
    d = TableDescription(file="", kind="concentrations", part="sheet:c", header_lines=[1], first_line=2, last_line=29,
                         time_unit="h", value_unit="ng/mL", zero_means_blq=True,
                         columns=[c(1, "subject"), c(2, "time"), c(3, "actual_time"), c(4, "value")])
    t = table("c.csv", conc, d)
    vomited = _said("study.excluded_subjects", "4", "Subject 4 vomited 0.75 h after dosing and was excluded.")
    sv = study_view("S", concentrations=[t], facts=[vomited])
    flags = {(p.code, p.message.split(":")[0]) for p in sv.problems if p.code.startswith("FLAG_")}
    assert flags == {("FLAG_PREDOSE", "subject 1"), ("FLAG_AUC_EXTRAPOLATED", "subject 2"), ("FLAG_TERMINAL_SPAN", "subject 2"),
                     ("FLAG_SAMPLE_WINDOW", "subject 3"), ("FLAG_VOMITING", "subject 4")}
    predose = next(p for p in sv.problems if p.code == "FLAG_PREDOSE")
    assert "12.0 % of its Cmax" in predose.message and "above 5 %" in predose.message
    window = next(p for p in sv.problems if p.code == "FLAG_SAMPLE_WINDOW")
    assert "subject 3" in window.message and "+30 min" in window.message
    vomit = next(p for p in sv.problems if p.code == "FLAG_VOMITING")
    assert vomit.severity == "warning" and "0.75 h" in vomit.message and "does not state the release" in vomit.message
    # flags, never deletions: subjects 1-3 stay in the modeling set (4 is out only because the client lists it)
    sets = {s.name: s.subjects for s in sv.sets}
    assert set(sets["modeling"]) == {"1", "2", "3"} and "4" in sets["dosed"]
    # for a modified-release product the rule does not apply; with no stated event, nothing is said
    mr = study_view("S", concentrations=[t], facts=[vomited], release="extended release")
    assert next(p for p in mr.problems if p.code == "FLAG_VOMITING").severity == "info"
    assert not any(p.code == "FLAG_VOMITING" for p in study_view("S", concentrations=[t]).problems)


# --- feature 5: observed data that know their statistic -------------------------------------------------------------

def test_a_client_mean_table_says_its_statistic_and_sem_becomes_sd_only_where_n_is_stated():
    from modeler_project.dataroom.observed import client_means

    wide = ("Subject,Treatment,0,1,2\n1,A,0,10,8\n2,A,0,12,6\n3,A,0,11,7\n"
            "Geo. mean,A,0,10.9,6.9\nGeo. SD,A,1,1.1,1.2\n")
    d = TableDescription(file="", kind="concentrations", part="sheet:w", header_lines=[1], first_line=2, last_line=6,
                         time_unit="h", value_unit="ng/mL",
                         columns=[c(1, "subject"), c(2, "treatment")] + [c(3 + i, "value", time=float(x)) for i, x in enumerate((0, 1, 2))])
    t = table("w.csv", wide, d)
    assert {s.subject for s in samples_from(t)[0]} == {"1", "2", "3"}       # "Geo. mean" is no subject
    (m,), problems = client_means(t)
    assert (m.group, m.statistic, m.spread) == ("A", "geometric_mean", "geometric_sd") and not problems
    assert [p.value for p in m.points] == [0, 10.9, 6.9] and m.statistic_as_written == "Geo. mean"
    down = "Time (h),Mean,SEM,N\n1,10,1.0,9\n2,8,0.5,9\n"
    d2 = TableDescription(file="", kind="concentrations", part="sheet:d", header_lines=[1], first_line=2, last_line=3,
                          time_unit="h", value_unit="ng/mL", columns=[c(1, "time"), c(2, "value"), c(3, "value"), c(4, "value")])
    (m,), _ = client_means(table("d.csv", down, d2))
    assert (m.statistic, m.spread, m.n) == ("arithmetic_mean", "sem", 9)
    assert [p.sd for p in m.points] == [pytest.approx(3.0), pytest.approx(1.5)] and "SEM × √n" in m.note
    assert "read as the arithmetic mean" in m.note
    no_n = "Time (h),Mean (SEM)\n1,10 (1.0)\n2,8 (0.5)\n"
    d3 = TableDescription(file="", kind="concentrations", part="sheet:n", header_lines=[1], first_line=2, last_line=3,
                          time_unit="h", value_unit="ng/mL", columns=[c(1, "time"), c(2, "value")])
    (m,), _ = client_means(table("n.csv", no_n, d3))
    assert (m.spread, [p.spread for p in m.points], [p.sd for p in m.points]) == ("sem", [1.0, 0.5], [None, None])
    assert "not turned into an SD" in m.note
    bare = "Time (h),Conc\n1,10\n2,8\n"
    (m,), problems = client_means(table("n.csv", bare, d3))
    assert m.statistic == "" and [p.code for p in problems] == ["STATISTIC_NOT_STATED"]


def test_the_plans_observed_rows_say_the_statistic_exactly():
    conc = ("Subject,Treatment,0,1,2,4\n1,A,0,10,8,4\n2,A,0,12,6,3\n3,A,0,11,7,3.5\n"
            "Geometric mean,A,0,10.9,6.9,3.5\nGeometric SD,A,1,1.1,1.2,1.2\nN,A,3,3,3,3\n")
    desc = TableDescription(file="D/c.csv", kind="concentrations", about="S-1", part="sheet:c", header_lines=[1],
                            first_line=2, last_line=7, time_unit="h", value_unit="ng/mL",
                            columns=[c(1, "subject"), c(2, "treatment")] + [c(3 + i, "value", time=float(x))
                                                                            for i, x in enumerate((0, 1, 2, 4))])
    part = parse_document(conc.encode(), "c.csv")
    from modeler_intake.room import document_parts

    desc = desc.model_copy(update={"part": document_parts(part)[0].name})
    room = _room({"c.csv": conc}, [Extraction(file="D/c.csv", tables=[desc])])
    rows = [r for r in room.inputs if r.block == "observed"]
    ours = next(r for r in rows if r.label.startswith("Mean profile"))
    theirs = next(r for r in rows if r.label.startswith("The client's mean profile"))
    assert "arithmetic mean ± SD (below the LLOQ as 0) and geometric mean" in str(ours.value)
    assert theirs.value == ("geometric mean ± geometric SD, N = 3 (as the table writes it: Geometric mean · Geometric SD)")
    assert theirs.status == "sponsor" and theirs.sources


# --- feature 6: the permeability guard ------------------------------------------------------------------------------

NOTES = ("Caco-2 Papp (A to B) of Exampleamide: 28 x 10^-6 cm/s.\n"
         "Metoprolol, the high-permeability reference compound, in the same assay: 25 x 10^-6 cm/s.\n"
         "Specific intestinal permeability fitted to the oral solution PK: 0.00012 cm/min.\n")
CARD = QuestionCard(question="q", products=[ProductRef(name="Exampleamide 100 mg", role="test")])


def _permeability_room(*keep: int):
    lines = NOTES.splitlines()
    facts = [Fact(field="substance.permeability", subject="Exampleamide", value="28", unit="10^-6 cm/s", quote=lines[0]),
             Fact(field="substance.permeability", subject="metoprolol", value="25", unit="10^-6 cm/s", quote=lines[1]),
             Fact(field="substance.permeability", subject="Exampleamide fitted", value="0.00012", unit="cm/min",
                  quote=lines[2])]
    return _room({"notes.md": NOTES}, [Extraction(file="D/notes.md", facts=[facts[i] for i in keep])], CARD)


def test_a_cell_assay_permeability_is_never_sent_and_asks_for_the_labs_reference_compounds():
    room = _permeability_room(0)
    row = next(r for r in room.inputs if r.name == "perm.intestinal")
    assert row.value is None and row.status == "missing" and "not in the delivery: a data request" in row.note
    (asked,) = [r for r in room.requests if "reference compounds" in r.title]
    assert asked.area == "C" and "about 100 ×" in asked.why
    # given in the delivery, the reference compounds are evidence beside it, never the drug's permeability
    room = _permeability_room(1, 0)
    row = next(r for r in room.inputs if r.name == "perm.intestinal")
    assert row.value is None and "metoprolol 25 10^-6 cm/s" in row.note and "not applied" in row.note
    assert not any("reference compounds" in r.title for r in room.requests)
    ref = next(v for v in room.substance if v.key == "substance.permeability.reference[metoprolol]")
    assert "reference compound" in ref.label and "calibration" in ref.note


def test_a_permeability_fitted_to_pk_is_labelled_fitted_never_measured():
    room = _permeability_room(2)
    row = next(r for r in room.inputs if r.name == "perm.intestinal")
    assert (row.value, row.unit, row.status, row.origin) == (0.00012, "cm/min", "sponsor", "fitted")
    assert row.label.endswith(", fitted") and "not a measurement" in row.note


# --- feature 7: dissolution checks ----------------------------------------------------------------------------------

def test_a_profile_says_too_few_units_a_bell_shape_and_a_likely_disintegration_lag():
    from modeler_project.dataroom.invitro import profile_checks

    rules = load_rules()
    codes = [p.code for p in profile_checks((5, 10, 15, 30, 45, 60), (2, 4, 40, 80, 92, 84), 6, rules)]
    assert codes == ["FEWER_UNITS", "BELL_SHAPE", "DISINTEGRATION_LAG"]
    fewer = profile_checks((5, 10), (50, 90), 6, rules)[0]
    assert "f2 needs at least 12" in fewer.message and "dissolution-similarity" in fewer.message   # the locked ruleset's
    assert profile_checks((5, 10, 15, 30), (30, 60, 80, 95), 12, rules) == []
    assert profile_checks((5, 10, 15, 30), (30, 60, 80, 77), 12, rules) == []        # a 3-point dip: within tolerance


def test_batches_of_one_product_tested_by_different_methods_are_said_once_per_product():
    from modeler_project.dataroom.invitro import method_checks

    def view(batch: str, product: str, rpm: float, medium: str = "pH 6.8 phosphate buffer") -> DissolutionView:
        return DissolutionView(id=f"{batch}-{rpm}-{medium}", product=product, batch=batch, medium=medium, ph=6.8,
                               apparatus="USP 2", rpm=rpm, volume_ml=900)

    same = [view("B1", "P", 50), view("B2", "P", 50)]
    assert method_checks(same) == []
    (said,) = method_checks([view("B1", "P", 50), view("B2", "P", 75), view("B2", "P", 75, "pH 1.2 HCl"),
                             view("B1", "P", 50, "pH 1.2 HCl")])
    assert said.code == "DISSOLUTION_METHODS_DIFFER" and "50 rpm" in said.message and "75 rpm" in said.message
    assert said.message.count("batches of P") == 1


# --- feature 8: which step limits absorption ------------------------------------------------------------------------

def test_the_dose_number_says_where_solubility_may_limit_absorption_and_the_sink_index_of_each_medium():
    from modeler_project.dataroom.invitro import dose_number, limiting_steps, sink_index

    assert dose_number(40, 0.0186, 250) == pytest.approx(8.6022, abs=1e-4)          # Do = 40 / (250 × 0.0186)
    rows = [SolubilityRow(medium="0.1 N HCl", ph=1.2, solubility_mg_ml=2.35),
            SolubilityRow(medium="Phosphate buffer", ph=6.81, solubility_mg_ml=0.0186)]
    (step,) = limiting_steps(rows, [("Exampleamide 40 mg", 40.0, "40 mg", ())])
    assert step.statements == ("solubility may limit absorption at pH 6.81 (Phosphate buffer) (dose number 8.6)",)
    (fine,) = limiting_steps(rows[:1], [("", 40.0, "40 mg", ())])
    assert "unlikely to limit absorption" in fine.statements[0]
    view = DissolutionView(id="d", product="P", medium="pH 6.8 phosphate buffer", ph=6.8, volume_ml=900)
    value, basis, low = sink_index(view, rows, 40.0)
    assert value == pytest.approx(0.4185, abs=1e-3) and "900 mL / 40 mg" in basis
    assert low is not None and low.code == "NOT_SINK" and low.severity == "info"
    acid = view.model_copy(update={"medium": "0.1 N HCl", "ph": 1.2})
    assert sink_index(acid, rows, 40.0)[0] == pytest.approx(52.875) and sink_index(acid, rows, 40.0)[2] is None
    assert sink_index(view, rows, None) == (None, "", None)                         # no dose: nothing claimed


# --- feature 9: excipients by function ------------------------------------------------------------------------------

def test_excipients_are_classed_by_function_and_a_test_versus_reference_difference_is_for_the_sme():
    from modeler_project.dataroom.invitro import composition_rows, excipient_checks

    text = ("Component,Function,Exampleamide 100 mg,Refamide 100 mg\n"
            "Exampleamide,Active,100.0,100.0\nMannitol,Filler,120.0,120.0\n"
            "Sodium lauryl sulfate,Wetting agent,3.6,\nCroscarmellose sodium,Disintegrant,8.0,12.0\n"
            "Kollisolv X,Wetting agent,2.0,2.0\nMagnesium stearate,Lubricant,2.0,2.0\n")
    d = TableDescription(file="", kind="composition", part="sheet:f", header_lines=[1], first_line=2, last_line=7,
                         columns=[c(1, "component"), c(2, "function"),
                                  c(3, "amount", group="Exampleamide 100 mg", unit="mg"),
                                  c(4, "amount", group="Refamide 100 mg", unit="mg")])
    rows = {r.component: r for r in composition_rows([table("f.csv", text, d)])}
    assert (rows["Mannitol"].excipient_class, rows["Mannitol"].class_by) == ("sugar_alcohol", "name")
    assert (rows["Kollisolv X"].excipient_class, rows["Kollisolv X"].class_by) == ("surfactant", "function")
    assert rows["Exampleamide"].excipient_class == "active" and rows["Magnesium stearate"].excipient_class == "other"
    assert rows["Croscarmellose sodium"].mg == {"Exampleamide 100 mg": 8.0, "Refamide 100 mg": 12.0}
    said = excipient_checks(list(rows.values()), {"Exampleamide 100 mg": "test", "Refamide 100 mg": "reference"})
    by_class = {p.message.split(":")[0]: p.message for p in said}
    assert set(by_class) == {"surfactants", "disintegrants"}                       # mannitol is the same in both
    assert "Sodium lauryl sulfate 3.6" in by_class["surfactants"] and "for the SME to judge" in by_class["surfactants"]
    assert "8 mg against 12 mg" in by_class["disintegrants"]
