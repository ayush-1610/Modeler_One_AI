"""D3: the strict check a quoted prose fact passes before it is kept (contracts §6.2, §8.5; plan §7.5). The label and
exactly one number of the field's class in one clause; code's number, unit, choice and name, never the model's; the
study and arm only as the paragraph or its heading writes them; every span a locator of the source. Software test data
(the made-up Exampleamide), never observed data."""

from __future__ import annotations

import io

import pdfplumber
import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import parse_locator, same_place
from modeler_intake.mapping.prose_check import ProseFactError, check_prose_fact
from modeler_intake.mapping_spec import ProseParagraph

pytestmark = pytest.mark.req("T-47")

WORD = synthetic.word_report()
PDF = synthetic.pdf_report()


def _para(text: str, *, index: int = 2, locator: str = "d:p:2-2", heading: str = "", heading_locator: str | None = None):
    return ProseParagraph(index=index, text=text, locator=locator, heading=heading, heading_locator=heading_locator)


def _refused(field, value, quote, paragraph, **labels) -> str:
    with pytest.raises(ProseFactError) as refused:
        check_prose_fact(field, value, quote, paragraph, **labels)
    return str(refused.value)


# --- the synthetic truth, as D2 hands its paragraphs ---------------------------------------------------------------------


def _word_paragraphs() -> dict[int, ProseParagraph]:
    import docx

    paragraphs = docx.Document(io.BytesIO(WORD.data)).paragraphs
    heading = paragraphs[0].text
    return {i: ProseParagraph(index=i, text=paragraphs[i - 1].text, locator=f"d:p:{i}-{i}", heading=heading,
                              heading_locator="d:p:1-1") for i in (2, 3)}


def _pdf_synopsis():
    """Page 1's synopsis as one paragraph (its words joined by spaces, heading apart, the page number left out) and the
    page's word boxes."""
    with pdfplumber.open(io.BytesIO(PDF.data)) as pdf:
        words = pdf.pages[0].extract_words()
    lines: dict[float, list[int]] = {}
    for i, w in enumerate(words, start=1):
        lines.setdefault(round(w["top"]), []).append(i)
    heading, *body, _footer = (lines[top] for top in sorted(lines))
    first, last = body[0][0], body[-1][-1]
    paragraph = ProseParagraph(index=1, text=" ".join(words[i - 1]["text"] for i in range(first, last + 1)),
                               locator=f"p:1/w:{first}-{last}", heading=" ".join(words[i - 1]["text"] for i in heading),
                               heading_locator=f"p:1/w:{heading[0]}-{heading[-1]}")

    def box(page: int, a: int, b: int):
        assert page == 1
        chosen = words[a - 1:b]
        return (min(w["x0"] for w in chosen), min(w["top"] for w in chosen), max(w["x1"] for w in chosen),
                max(w["bottom"] for w in chosen))

    return paragraph, box


def _clause(text: str, word: str) -> str:
    """The sentence of `text` that writes `word`: the quote a model gives."""
    return next(s.strip() for s in text.replace(". ", ".\n").split("\n") if word in s)


def test_the_prose_truth_of_the_word_report_is_read_with_its_true_spans():
    paragraphs = _word_paragraphs()
    truth = [v for v in WORD.values if v.table == ""]
    assert {v.field for v in truth} == {"n", "dose"}
    for value in truth:
        number = parse_locator(value.locator).paragraph
        paragraph = paragraphs[number]
        study = value.study if dict(value.locators).get("study", "").startswith(f"d:p:{number}/") else None
        fact = check_prose_fact(value.field, value.value, _clause(paragraph.text, value.value), paragraph, study=study)
        assert (fact.value, fact.unit or "", fact.locator) == (float(value.value), value.unit, value.locator)
        if study is not None:
            assert (fact.study_label, fact.study_locator) == (value.study, dict(value.locators)["study"])
        else:   # the dose's sentence names no study: with no label, the ledger's rule applies (contracts §6.3)
            assert _refused(value.field, value.value, _clause(paragraph.text, value.value), paragraph,
                            study=value.study).startswith("the study label '230-27' is not written in paragraph 3")


def test_the_prose_truth_of_the_pdf_synopsis_is_read_with_its_true_word_spans():
    paragraph, box = _pdf_synopsis()
    truth = [v for v in PDF.values if v.table == ""]
    assert {v.field for v in truth} == {"dose", "n", "food_state"}
    for value in truth:
        fact = check_prose_fact(value.field, value.value, _clause(paragraph.text, value.value), paragraph,
                                study=value.study, pdf_box=box)
        expected = value.value if value.field == "food_state" else float(value.value)
        assert (fact.value, fact.unit or "") == (expected, value.unit)
        assert same_place(parse_locator(fact.locator), parse_locator(value.locator))      # identities, never boxes
        assert same_place(parse_locator(fact.study_locator), parse_locator(dict(value.locators)["study"]))
    with pytest.raises(ValueError, match="pdf_box"):
        check_prose_fact("n", 24, "The study enrolled 24 healthy subjects.", paragraph)


# --- one clause, its label and exactly one number ------------------------------------------------------------------------


def test_the_label_and_exactly_one_number_in_the_clause():
    paragraph = _para("Study 230-23 enrolled 24 subjects. 24 were enrolled; all were healthy volunteers. "
                      "The study enrolled 24 healthy subjects.")
    fact = check_prose_fact("n", 24, "The study enrolled 24 healthy subjects.", paragraph)
    at = paragraph.text.index("24 healthy")
    assert (fact.value, fact.locator) == (24.0, f"d:p:2/ch:{at}-{at + 2}")
    # the label is in another clause than the number
    assert "does not name n" in _refused("n", 24, "24 were enrolled; all were healthy volunteers", paragraph)
    # "230-23" is two numbers: a study label and a count do not share a clause for a field with no unit class
    assert "holds 3 numbers of n (230, 23, 24)" in _refused("n", 24, "Study 230-23 enrolled 24 subjects", paragraph)
    # a whole number
    assert "whole number" in _refused("n", 24.5, "with a mean of 24.5 subjects per site", _para("with a mean of 24.5 "
                                                                                                 "subjects per site"))


def test_a_mean_with_its_sd_in_one_clause_is_refused():
    """"mean 12.4 (SD 3.1)": two numbers of the class in the clause, so neither is a fact."""
    paragraph = _para("The mean Cmax was 12.4 (SD 3.1) ng/mL. The mean age was 34.2 years (SD 8.1). "
                      "The mean Cmax of the metabolite was 4.4 ng/mL.")
    assert "holds 2 numbers of pk.Cmax (12.4, 3.1)" in _refused("pk.Cmax", 12.4, "The mean Cmax was 12.4 (SD 3.1) ng/mL",
                                                                paragraph)
    assert "holds 2 numbers of age_mean" in _refused("age_mean", 34.2, "The mean age was 34.2 years (SD 8.1)", paragraph)
    fact = check_prose_fact("pk.Cmax", 4.4, "The mean Cmax of the metabolite was 4.4 ng/mL", paragraph)
    assert (fact.value, fact.unit) == (4.4, "ng/mL")                # a unit of a table, read as written for class other


@pytest.mark.parametrize(("sentence", "written", "unit"), [
    ("Subjects received a single oral dose of 50 mg.", "50", "mg"),
    ("Subjects received a single oral dose of 0.5 g.", "0.5", "g"),
    ("Subjects received a single oral dose of 500 µg.", "500", "µg"),
    ("Subjects received a single oral dose of 500 mcg.", "500", "mcg"),
    ("Subjects received a single oral 250mg dose.", "250", "mg"),
    ("Subjects received a dose of 2 mg/kg.", "2", "mg/kg"),
    ("In study 230-23 subjects were dosed with 50 mg.", "50", "mg"),     # 230 and 23 are no mass: one number of the class
])
def test_a_dose_in_mg_g_and_µg_is_one_number_of_the_mass_class(sentence, written, unit):
    fact = check_prose_fact("dose", float(written), sentence, _para(sentence))
    assert (fact.value, fact.unit) == (float(written), unit)
    assert sentence[slice(*_chars(fact.locator))] == written


def _chars(locator: str) -> tuple[int, int]:
    parsed = parse_locator(locator)
    return parsed.start, parsed.end


def test_the_times_100_reading_is_refused():
    paragraph = _para("Of the 24 subjects, 45% were female.")
    assert "no times 100" in _refused("percent_female", 0.45, "Of the 24 subjects, 45% were female.", paragraph)
    fact = check_prose_fact("percent_female", 45, "Of the 24 subjects, 45% were female.", paragraph)
    assert (fact.value, fact.unit, fact.locator) == (45.0, "%", "d:p:2/ch:20-22")


def test_the_unit_is_parsed_by_code_and_the_number_stored_is_codes():
    paragraph = _para("Each subject was dosed with 1,5 mg of Exampleamide; the reference arm was dosed with 1,000 mg.")
    fact = check_prose_fact("dose", "1.5", "Each subject was dosed with 1,5 mg of Exampleamide", paragraph)
    assert (fact.value, fact.unit, fact.locator) == (1.5, "mg", "d:p:2/ch:28-31")
    # the model's unit conversion is not a reading: 0.0015 g is not written
    assert "code reads 1,5 mg" in _refused("dose", 0.0015, "Each subject was dosed with 1,5 mg of Exampleamide", paragraph)
    # "1,000": a thousands group or a decimal comma, never guessed
    assert "no clause" in _refused("dose", 1000, "the reference arm was dosed with 1,000 mg", paragraph)
    # the number as the sentence writes it, decimal comma included
    assert check_prose_fact("dose", "1,5", "Each subject was dosed with 1,5 mg of Exampleamide", paragraph).value == 1.5
    # a value with its unit is not a number
    assert "not '1.5 mg'" in _refused("dose", "1.5 mg", "Each subject was dosed with 1,5 mg of Exampleamide", paragraph)
    # the micro sign is kept as written, never renamed
    micro = _para("A single dose of 500 µg was given.")
    assert check_prose_fact("dose", 500, "A single dose of 500 µg was given.", micro).unit == "µg"
    assert "code reads 500 µg" in _refused("dose", 0.5, "A single dose of 500 µg was given.", micro)
    # U+2212 is a minus sign
    signed = _para("The mean change in weight was \N{MINUS SIGN}1.5 kg over the study.")
    fact = check_prose_fact("weight_mean_kg", -1.5, "The mean change in weight was \N{MINUS SIGN}1.5 kg", signed)
    assert (fact.value, fact.unit, fact.locator) == (-1.5, "kg", "d:p:2/ch:30-34")


def test_a_name_is_read_by_names_in_as_one_contiguous_name():
    paragraph = _para("Study 230-23 and study 231-24 were conducted at one site.")
    # every word and number of "230-24" is in the clause (today's bag-of-words text_in would pass it): no contiguous name
    assert "no clause" in _refused("study_id", "230-24", "Study 230-23 and study 231-24 were conducted", paragraph)
    fact = check_prose_fact("study_id", "230 23", "Study 230-23 and study 231-24 were conducted", paragraph)
    assert (fact.value, fact.locator) == ("230-23", "d:p:2/ch:6-12")           # as the paragraph writes it
    fact = check_prose_fact("study_id", "231-24", "Study 230-23 and study 231-24 were conducted", paragraph)
    assert (fact.value, fact.locator) == ("231-24", "d:p:2/ch:23-29")
    # a name in a clause that does not carry the field's label: "and 231-24 were conducted" names no study
    assert "does not name study_id" in _refused("study_id", "231-24", "Study 230-23 and 231-24 were conducted",
                                               _para("Study 230-23 and 231-24 were conducted at one site."))
    batch = _para("The tablets came from lot L2301-A.")
    assert check_prose_fact("batch", "l2301a", "The tablets came from lot L2301-A.", batch).value == "L2301-A"
    assert "does not name batch" in _refused("batch", "L2301-A", "The tablets came from L2301-A", _para(
        "The tablets came from L2301-A."))


def test_a_choice_is_read_by_read_choice():
    paragraph = _para("Subjects were dosed after a high-fat breakfast. The drug was given by inhalation.")
    fact = check_prose_fact("food_state", "fed", "Subjects were dosed after a high-fat breakfast", paragraph)
    assert (fact.value, fact.locator) == ("fed", "d:p:2/ch:28-36")              # "high-fat": the words that state it
    assert "code reads fed" in _refused("food_state", "fasted", "Subjects were dosed after a high-fat breakfast",
                                        paragraph)
    # "other" only with the word
    assert "no clause" in _refused("route", "other", "The drug was given by inhalation", paragraph)
    other = _para("The drug was given by another, other route.")
    assert check_prose_fact("route", "other", "The drug was given by another, other route.", other).value == "other"
    design = _para("It was a single-dose study.")
    fact = check_prose_fact("design", "SD", "It was a single-dose study.", design)
    assert (fact.value, fact.locator) == ("SD", "d:p:2/ch:9-20")


def test_a_study_label_must_be_written_in_the_paragraph_or_its_heading():
    paragraph = _para("Each subject received a single oral dose of 20 mg.", index=3, locator="d:p:3-3",
                      heading="Study 230-27: design", heading_locator="d:p:1-1")
    fact = check_prose_fact("dose", 20, "a single oral dose of 20 mg", paragraph, study="230-27", arm="Design")
    assert (fact.study_label, fact.study_locator) == ("230-27", "d:p:1/ch:6-12")       # its span in the heading
    assert (fact.arm_label, fact.arm_locator) == ("design", "d:p:1/ch:14-20")
    assert "study label '230-28'" in _refused("dose", 20, "a single oral dose of 20 mg", paragraph, study="230-28")
    assert "arm label 'Cohort 2'" in _refused("dose", 20, "a single oral dose of 20 mg", paragraph, arm="Cohort 2")
    in_text = _para("In Cohort 2 of study 230-27 each subject received a single oral dose of 30 mg.")
    fact = check_prose_fact("dose", 30, "each subject received a single oral dose of 30 mg", in_text, study="230-27",
                            arm="cohort 2")
    assert (fact.arm_label, fact.arm_locator, fact.study_locator) == ("Cohort 2", "d:p:2/ch:3-11", "d:p:2/ch:21-27")


# --- a range, a quote cut short, a part of a longer name, an ambiguous thousands group ----------------------------------


@pytest.mark.parametrize("sentence", [
    "Subjects were dosed with single oral doses of 10-30 mg of Exampleamide.",
    "Subjects were dosed with single oral doses of 10 to 30 mg of Exampleamide.",
    "Subjects were dosed with single oral doses of 10, 20 or 30 mg of Exampleamide.",
    "Subjects were dosed with single oral doses of 10 and 30 mg of Exampleamide.",
])
def test_a_range_or_a_list_of_doses_states_no_one_dose(sentence):
    """Only 30 is followed by "mg", yet "10-30 mg" states no dose of 30 mg: the numbers joined to it are doses too."""
    paragraph = _para(sentence)
    quote = sentence.removesuffix(" of Exampleamide.")
    for value in (10, 30):
        with pytest.raises(ProseFactError):
            check_prose_fact("dose", value, quote, paragraph)
    if " and " not in sentence:                                      # " and " is a clause break: the list spans two
        assert "states a range or a list of dose" in _refused("dose", 30, quote, paragraph)
    # "Day 1, 50 mg" is no list, and an interval's start and end are the two ends of one range
    assert check_prose_fact("dose", 50, "On Day 1, 50 mg was dosed", _para("On Day 1, 50 mg was dosed.")).value == 50.0
    urine = _para("Urine was collected over the interval 0-24 h after dosing.")
    end = check_prose_fact("interval_end_h", 24, "Urine was collected over the interval 0-24 h", urine)
    start = check_prose_fact("interval_start_h", 0, "Urine was collected over the interval 0-24 h", urine)
    assert (end.value, end.unit, start.value, start.unit) == (24.0, "h", 0.0, "h")


def test_a_quote_cut_short_does_not_hide_the_clauses_other_numbers():
    fed = _para("In the fasted state the Cmax of Exampleamide was 12.4 ng/mL, 15.2 ng/mL fed, in 24 subjects.")
    assert "holds 3 numbers of pk.Cmax" in _refused("pk.Cmax", 12.4, "the Cmax of Exampleamide was 12.4 ng/mL", fed)
    mean = _para("The mean Cmax was 12.4 ng/mL (SD 3.1 ng/mL) after a single dose.")
    assert "holds 2 numbers of pk.Cmax (12.4, 3.1)" in _refused("pk.Cmax", 12.4, "The mean Cmax was 12.4 ng/mL", mean)
    # the label is still read in the part of the clause the quote copies
    enrolled = _para("Study 230-27 was a crossover study. It enrolled 18 healthy volunteers.")
    assert "does not name n" in _refused("n", 18, "was a crossover study. It enrolled 18", enrolled)
    assert check_prose_fact("n", 18, "It enrolled 18 healthy volunteers", enrolled).value == 18.0


def test_a_name_is_never_a_part_of_a_longer_name():
    cohort = _para("In Cohort 10, subjects received a single dose of 30 mg Exampleamide orally.")
    assert "arm label 'Cohort 1'" in _refused("dose", 30, "subjects received a single dose of 30 mg", cohort, arm="Cohort 1")
    assert check_prose_fact("dose", 30, "subjects received a single dose of 30 mg", cohort, arm="cohort 10").arm_label == (
        "Cohort 10")
    study = _para("Study 230-23 enrolled subjects of Treatment B.")
    for part in ("230-2", "30-23", "0-2"):
        assert "no clause" in _refused("study_id", part, "Study 230-23 enrolled subjects", study)
    assert "arm label 'A'" in _refused("study_id", "230-23", "Study 230-23 enrolled subjects", study, arm="A")
    assert check_prose_fact("study_id", "230-23", "Study 230-23 enrolled subjects", study, arm="B").arm_label == "B"
    batch = _para("Tablets of batch B1234 were used.")
    assert "no clause" in _refused("batch", "B123", "Tablets of batch B1234 were used.", batch)
    metabolite = _para("The analyte measured was Exampleamide-M1 in plasma.")
    assert "no clause" in _refused("analyte", "Exampleamide", "The analyte measured was Exampleamide-M1", metabolite)
    assert check_prose_fact("analyte", "Exampleamide-M1", "The analyte measured was Exampleamide-M1",
                            metabolite).value == "Exampleamide-M1"
    # a later whole occurrence is found past an earlier part of a longer name
    both = _para("Cohort 10 and Cohort 1 were dosed with 30 mg each.")
    assert check_prose_fact("dose", 30, "were dosed with 30 mg each", both, arm="Cohort 1").arm_locator == "d:p:2/ch:14-22"


def test_a_thousands_group_with_a_point_is_as_ambiguous_as_with_a_comma():
    paragraph = _para("Subjects were dosed with 1.000 mg; the reference arm was dosed with 1,000 mg.")
    for value, quote in ((1, "Subjects were dosed with 1.000 mg"), (1000, "Subjects were dosed with 1.000 mg"),
                         (1000, "the reference arm was dosed with 1,000 mg"), (1, "the reference arm was dosed with 1,000 mg")):
        assert "no clause" in _refused("dose", value, quote, paragraph)
    lloq = _para("The LLOQ was 0.500 ng/mL.")
    assert check_prose_fact("lloq", 0.5, "The LLOQ was 0.500 ng/mL.", lloq).value == 0.5     # no group starts with 0


def test_the_locator_spans_the_number_in_each_kind_of_paragraph():
    sentence = "Each subject received a single oral dose of 20 mg."
    at = sentence.index("20")
    assert check_prose_fact("dose", 20, sentence, _para(sentence)).locator == f"d:p:2/ch:{at}-{at + 2}"
    # a paragraph given as a span: its text starts at that character
    assert check_prose_fact("dose", 20, sentence, _para(sentence, locator="d:p:5/ch:10-60")).locator == \
        f"d:p:5/ch:{at + 10}-{at + 12}"
    # text lines: the line that holds the number
    lines = _para("Study design\n" + sentence, locator="x:l:4-5")
    assert check_prose_fact("dose", 20, sentence, lines).locator == f"x:l:5/ch:{at}-{at + 2}"
    # a PDF paragraph: the word's number on the page and the box of that word
    words = _para(sentence, locator="p:3/w:11-20")
    fact = check_prose_fact("dose", 20, sentence, words, pdf_box=lambda page, a, b: (10.0 * a, 100.0, 10.0 * b + 8, 110.0))
    assert fact.locator == "p:3/w:19-19@190.00,100.00,198.00,110.00"
    # whitespace and a line-break hyphen in the paragraph do not move the span
    broken = _para("Each subject received a single oral dos-\n ing of  20 mg.")
    fact = check_prose_fact("dose", 20, "a single oral dosing of 20 mg", broken)
    assert broken.text[slice(*_chars(fact.locator))] == "20"


def test_a_quote_not_in_the_paragraph_and_a_table_are_refused():
    paragraph = _para("Each subject received a single oral dose of 20 mg.")
    assert "not in paragraph 2" in _refused("dose", 20, "a single dose of 20 mg", paragraph)      # altered
    assert "not in paragraph 2" in _refused("dose", 20, "20 mg", paragraph)                      # too short to place
    assert "not a field" in _refused("dosage", 20, "a single oral dose of 20 mg", paragraph)
    table = _para("Each subject received a single oral dose of 20 mg.", locator="d:t:1")
    assert "tables are never read as prose" in _refused("dose", 20, "a single oral dose of 20 mg", table)
