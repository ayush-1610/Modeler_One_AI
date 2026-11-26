"""The Data room put together (plan 2026-11-21 v2 §5-§8): from the agents' descriptions and quoted facts, code reads
and checks every value, joins them across files, applies the rules, and proposes the decisions, the data requests, the
simulation plan and the PK-Sim inputs. Nothing is invented: what no file gives is Missing, with a data request.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from modeler_intake.room import document_text, unmarked
from modeler_intake.room_specs import Extraction, QuestionCard
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom import checklist
from modeler_project.dataroom.bestats import be_results, csr_values
from modeler_project.dataroom.clinical import (
    _code_key,
    analyte_of,
    analytes_in,
    assignments,
    dose_arms,
    for_analyte,
    samples_from,
    study_view,
    subject_id,
    unnamed_lines,
)
from modeler_project.dataroom.detectors import detect
from modeler_project.dataroom.dosecard import dose_card
from modeler_project.dataroom.extract import check_fact, number_of, parse_number, read_table
from modeler_project.dataroom.invitro import (
    batch_products,
    composition_rows,
    dissolution_views,
    excipient_checks,
    f2_pairs,
    limiting_steps,
    method_checks,
    named_in,
    sink_index,
    solubility_from_facts,
    solubility_rows,
)
from modeler_project.dataroom.layout import build_layout, required_from_drafts
from modeler_project.dataroom.model import (
    Arm,
    CheckedFact,
    Chip,
    ClientMean,
    DataRequest,
    DataRoomView,
    DissolutionView,
    FileView,
    InputRow,
    Option,
    PlanRow,
    Problem,
    ReadTable,
    RoomDecision,
    RoomStudy,
    Section,
    SolubilityRow,
    Value,
)
from modeler_project.dataroom.observed import statistic_words
from modeler_project.dataroom.rules import Rules, load_rules
from pbpk_domain.cpf.formulations import WEIBULL_PARAMETERS

# The PK-Sim human population databases (harvested: services/engine-worker/golden/catalog.json "populations") a study's
# stated ethnicity is matched to; Pregnant and Preterm are special populations, not offered here.
POPULATIONS = ("European_ICRP_2002", "Asian_Tanaka_1996", "Japanese_Population", "WhiteAmerican_NHANES_1997",
               "BlackAmerican_NHANES_1997", "MexicanAmericanWhite_NHANES_1997")
_ETHNICITY = (("japanese", "Japanese_Population"), ("mexican", "MexicanAmericanWhite_NHANES_1997"),
              ("african", "BlackAmerican_NHANES_1997"), ("black", "BlackAmerican_NHANES_1997"),
              ("white american", "WhiteAmerican_NHANES_1997"), ("asian", "Asian_Tanaka_1996"),
              ("indian", "Asian_Tanaka_1996"), ("chinese", "Asian_Tanaka_1996"), ("korean", "Asian_Tanaka_1996"),
              ("caucasian", "European_ICRP_2002"), ("european", "European_ICRP_2002"), ("white", "European_ICRP_2002"))
# How a decision names each database to a person (the option's id is the harvested name, which the PK-Sim inputs show)
POPULATION_LABELS = {"European_ICRP_2002": "European (ICRP 2002)", "Asian_Tanaka_1996": "Asian (Tanaka 1996)",
                     "Japanese_Population": "Japanese", "WhiteAmerican_NHANES_1997": "White American (NHANES 1997)",
                     "BlackAmerican_NHANES_1997": "Black American (NHANES 1997)",
                     "MexicanAmericanWhite_NHANES_1997": "Mexican American (NHANES 1997)"}
# The PK-Sim meal templates (harvested: catalog.json "event_templates")
MEAL_STANDARD, MEAL_HIGH_FAT = "Meal: Standard (Human)", "Meal: High-fat breakfast (Human)"
# Compound parameters: CPF id, PK-Sim name (pbpk_domain/parameters/registry.yaml), the fact field, the unit stored
# (the label is the registry's PK-Sim name where it has one, else a plain label)
COMPOUND = (("phys.mw", "Molecular weight", "substance.mw", "g/mol"),
            ("phys.pka.base.0", "pKa (basic)", "substance.pka", ""),
            ("phys.logp", "Lipophilicity", "substance.logp", "Log Units"),
            ("phys.solubility.ref", "Solubility at reference pH", "substance.solubility", "mg/ml"),
            ("bind.fu", "Fraction unbound (plasma, reference value)", "adme.fu", "fraction"),
            ("dist.bp_ratio", "Blood-to-plasma ratio", "adme.bp_ratio", ""),
            ("perm.intestinal", "Specific intestinal permeability (transcellular)", "substance.permeability", "cm/min"))
# a permeability measured in a cell or membrane assay, as files write it
_CELL_ASSAY = re.compile(r"(?i)caco|mdck|pampa|\bpapp\b|apparent\s+permeab|lls?-?pk1|\bcm\s*/\s*s(?:ec)?\b|\bnm\s*/\s*s\b|10\s*[-−]\s*6")
# Which checklist topics a fact field or a table kind covers (the requirement checklist reads the same map)
_TOPIC_FIELDS = checklist.TOPIC_FIELDS
_TOPIC_TABLES = checklist.TOPIC_TABLES
_LITERATURE_TOPICS = {"literature", "label"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", text.lower()).strip()


def _same_study(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (_norm(a) == _norm(b) or _norm(a).replace(" ", "") in _norm(b).replace(" ", "")
                                    or _norm(b).replace(" ", "") in _norm(a).replace(" ", ""))


class Inputs:
    """What the Data room is assembled from (the store's state): the files and their read documents, the question card,
    the agents' answers per file, the modeler's decisions, values entered by a person, request edits."""

    def __init__(self, *, files: Sequence[FileView], docs: Mapping[str, SourceDocument], question: QuestionCard | None = None,
                 question_confirmed: bool = False, extractions: Sequence[Extraction] = (),
                 decisions: Mapping[str, Mapping[str, str]] | None = None, entered: Sequence[Value] = (),
                 request_edits: Mapping[str, Mapping[str, str]] | None = None,
                 reviews: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                 writing: Mapping[str, Mapping[str, str]] | None = None) -> None:
        self.files, self.docs, self.question, self.question_confirmed = files, docs, question, question_confirmed
        self.extractions, self.decisions, self.entered = extractions, dict(decisions or {}), entered
        self.request_edits = dict(request_edits or {})
        self.reviews = dict(reviews or {})
        self.writing = dict(writing or {})


def _value_status(facts: Sequence[CheckedFact], literature_files: set[str], tolerance: float) -> tuple[str, list[CheckedFact]]:
    """sponsor (one source), verified (sources in two files agree), conflict (they differ), literature (only papers,
    labels, databases)."""
    files = {f.chip.file for f in facts if f.chip}
    numbers = [f.number for f in facts if f.number is not None]
    if len(numbers) == len(facts) and numbers:
        agree = max(numbers) - min(numbers) <= tolerance / 100 * max(abs(x) for x in numbers)
    else:
        agree = len({_norm(f.fact.value) for f in facts}) == 1
    if not agree:
        return "conflict", list(facts)
    if all(f.chip and f.chip.file in literature_files for f in facts):
        return "literature", list(facts)
    return ("verified" if len(files) > 1 else "sponsor"), list(facts)


def _values(facts: Sequence[CheckedFact], prefix: str, labels: Mapping[str, str], literature_files: set[str],
            rules: Rules) -> list[Value]:
    groups: dict[tuple[str, str], list[CheckedFact]] = defaultdict(list)
    for f in facts:
        if f.ok and f.fact.field.startswith(prefix):
            subject = _norm(f.fact.subject or f.fact.product)
            if f.fact.field == "substance.pka":
                # an ampholyte states an acidic and a basic pKa: two values, not a conflict (a new delivery, 2026-11-24)
                subject += f"|{pka_type(f'{f.fact.value} {f.fact.quote}') or f.number}"
            groups[(f.fact.field, subject)].append(f)
    out = []
    for (field, _subject), got in sorted(groups.items()):
        status, _ = _value_status(got, literature_files, rules.conflicts.relative_tolerance_percent)
        first = got[0]
        others = tuple(Value(key=field, label=labels.get(field, field), value=g.number if g.number is not None else g.fact.value,
                             unit=g.fact.unit, as_written=g.fact.value, status="sponsor", sources=(g.chip,) if g.chip else ())
                       for g in got[1:]) if status == "conflict" else ()
        out.append(Value(key=field + (f"[{first.fact.subject}]" if first.fact.subject else ""), label=labels.get(field, field),
                         value=first.number if first.number is not None else first.fact.value, unit=first.fact.unit,
                         as_written=first.fact.value, status=status,  # type: ignore[arg-type]
                         sources=tuple(g.chip for g in got if g.chip), note=first.fact.note, others=others))
    return out


# a demographics column's unit -> the factor to PK-Sim's (age in years, weight in kg, height in cm)
_UNIT_TO_PKSIM = {("height", "m"): 100.0, ("height", "in"): 2.54, ("height", "inch"): 2.54, ("weight", "lb"): 0.45359237,
                  ("weight", "lbs"): 0.45359237, ("age", "months"): 1 / 12}


def _demographics(tables: Sequence[ReadTable], members: Sequence[str]) -> dict[str, float | str | int]:
    """Mean, SD and range of age, weight and height over the subjects of a set; the sexes counted."""
    rows: dict[str, dict[str, str]] = {}
    factors: dict[str, float] = {}
    for table in tables:
        for row in table.rows:
            if row.summary:
                continue
            one = {c.role: c.text for c in row.cells}
            for c in row.cells:
                factor = _UNIT_TO_PKSIM.get((c.role, c.unit.strip().lower()))
                if factor:
                    factors[c.role] = factor
            if one.get("subject", "").strip():
                rows[subject_id(one["subject"])] = one
    chosen = [rows[s] for s in members if s in rows] or list(rows.values())
    out: dict[str, float | str | int] = {"n": len(chosen)}
    for role in ("age", "weight", "height", "bmi"):
        xs = [x * factors.get(role, 1.0) for r in chosen if (x := parse_number(r.get(role, ""))) is not None]
        if xs:
            out[f"{role}_mean"] = round(statistics.fmean(xs), 2)
            out[f"{role}_sd"] = round(statistics.stdev(xs), 2) if len(xs) > 1 else 0.0
            out[f"{role}_min"], out[f"{role}_max"] = min(xs), max(xs)
    sexes = [r.get("sex", "").strip().upper()[:1] for r in chosen if r.get("sex", "").strip()]
    if sexes:
        out["male"], out["female"] = sexes.count("M"), sexes.count("F")
    return out


_CODE = re.compile(r"^\s*(?:treatment\s+)?([A-Z][A-Z0-9]{0,2}|\d{1,2})\s*[=:]\s*(.+?)\s*$", re.IGNORECASE)


def _code_pairs(text: str) -> list[tuple[str, str]]:
    """The codes a sentence defines: "B = test product; A = reference product", "A: Refamide 100 mg (Lot R-12).
    Treatment B: Exampleamide 100 mg"; each meaning stops at ";", at a sentence's end or at the next code."""
    pieces = re.split(r";|\n|\.\s+(?=\S)|,\s*(?=(?:treatment\s+)?[A-Z][A-Z0-9]{0,2}\s*[=:])", text, flags=re.IGNORECASE)
    out = []
    for piece in pieces:
        m = _CODE.match(piece)
        if m and m.group(1).upper() == m.group(1):
            out.append((m.group(1), m.group(2).rstrip(".")))
    return out


def _word(word: str, text: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text.lower()) is not None


def population_of(text: str) -> str | None:
    """The harvested PK-Sim population a stated ethnicity matches, by whole words, the longest phrase first ("white
    American" before "white"; "Caucasian" is not "Asian")."""
    for word, db in sorted(_ETHNICITY, key=lambda wd: -len(wd[0])):
        if _word(word, text):
            return db
    return None


def sex_of(text: str) -> str | None:
    """MALE, FEMALE, MIXED or None from words ("male", "men", "women", "female", "both sexes")."""
    female = any(_word(w, text) for w in ("female", "females", "women", "woman"))
    male = any(_word(w, text) for w in ("male", "males", "men", "man"))
    if _word("both sexes", text) or (male and female):
        return "MIXED"
    return "FEMALE" if female else ("MALE" if male else None)


def pka_type(text: str) -> str | None:
    t = text.lower()
    acid = any(w in t for w in ("acid", "acidic", "carboxyl", "phenol", "sulfonamide"))
    base = any(w in t for w in ("base", "basic", "amine", "amino", "piperidine", "pyridine"))
    return None if acid == base else ("acid" if acid else "base")


def fraction_unbound(value: float, unit: str, text: str) -> tuple[float | None, str]:
    """The fraction unbound from a binding value as written: a fraction (0-1) as is; a percentage bound or unbound by
    the words beside it ("95 % bound", "fu 5 %"); None with the reason when the words do not say which."""
    percent = "%" in unit or "%" in text or value > 1
    if not percent:
        return (value, "") if 0 <= value <= 1 else (None, f"{value:g} is not a fraction")
    t = text.lower()
    unbound = any(w in t for w in ("unbound", "free fraction", "fraction unbound", "fu "))
    bound = not unbound and any(w in t for w in ("bound", "binding"))
    if unbound:
        return round(value / 100, 6), f"{value:g} % unbound"
    if bound:
        return round(1 - value / 100, 6), f"from {value:g} % bound"
    return None, f"{value:g} %: the file does not say bound or unbound"


_TIME_WORDS = r"(h|hr|hrs|hour|hours|min|mins|minute|minutes)"


def food_of(text: str) -> str | None:
    """An arm's food state as its definition words it: "fed" (fed, a meal, a breakfast, with food), "fasted" (fasted,
    fasting, an empty stomach); None when it says neither. "Fed" wins when both are written ("a high-fat breakfast
    after an overnight fast")."""
    low = text.lower()
    if re.search(r"\bfed\b|\bmeal\b|breakfast|with food|high[- ]fat|\bfed state", low):
        return "fed"
    if re.search(r"\bfast(?:ed|ing)?\b|empty stomach", low):
        return "fasted"
    return None


def meal_times(text: str) -> list[float] | None:
    """Meal times in hours after the dose (negative: before it) from words: "lunch 4 h and dinner 10 h after dosing",
    "30 minutes before dosing", "at 4, 8 and 12 hours post-dose"; None when no time is written with its unit (a clock
    time such as "07:30" is not a time after the dose). The first direction word after a time decides it ("dinner 10 h
    after dosing, breakfast 30 min before" is 10 and −0.5), and a dose given after the meal puts the meal before the dose
    ("the dose 30 minutes after the start of breakfast" is −0.5): a meal's sign is what places it on the fed arms only."""
    out: list[float] = []
    for m in re.finditer(r"((?:\d+(?:\.\d+)?\s*(?:,|and|&|or)\s*)*\d+(?:\.\d+)?)\s*" + _TIME_WORDS + r"\b(?=(.{0,60}))",
                         text, re.IGNORECASE):
        numbers = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(1))]
        factor = 1 / 60 if m.group(2).lower().startswith("min") else 1.0
        way = re.search(r"\b(before|prior|pre|after|post)", m.group(3), re.IGNORECASE)
        before = way is not None and (way.group(1).lower() in ("before", "prior", "pre") or re.match(
            r"\s*(?:the\s+)?(?:start|beginning|onset|initiation)\s+of\b|\s*(?:a\s+|the\s+)?(?:[\w-]+\s+){0,2}?"
            r"(?:meal|breakfast)\b", m.group(3)[way.end():], re.IGNORECASE) is not None)
        out.extend(round((-x if before else x) * factor, 4) for x in numbers)
    return sorted(set(out)) or None


#: what every simulation plan row says: the room proposes, the frozen MS-01 split in the MAP decides (plan §7, B9)
PLAN_PROPOSED = "proposed; the MS-01 split decides"
#: what an oral study record without its water means (StudyRecord.water_ml_per_kg None), said wherever it is not given
WATER_DEFAULT = "PK-Sim's default (3.5 ml/kg) applies unless it is given"

_NUMBER_TEXT = r"\d+(?:\.\d+)?"
_RANGE = re.compile(rf"between\s+({_NUMBER_TEXT})\s+and\s+({_NUMBER_TEXT})|({_NUMBER_TEXT})\s*(?:-|–|—|to)\s*({_NUMBER_TEXT})",
                    re.IGNORECASE)
_CENTRAL = re.compile(r"\b(mean|average|median)\b", re.IGNORECASE)
# an inclusion limit, not a summary ("18 years or older", "≥ 18", "up to 55"): no central value is read from it
_LIMIT = re.compile(r"[≥≤<>]|\b(?:older|over|above|at least|or more|younger|under|up to|minimum|maximum)\b", re.IGNORECASE)
# a demographic's units in PK-Sim's own (years, kg, cm; none written: those), and the unit words looked for in its text,
# in this order; another unit is converted by `_UNIT_TO_PKSIM` or, unknown, not used
_PKSIM_UNIT = {"age": ("", "years", "year", "yrs", "yr", "y"), "weight": ("", "kg"), "height": ("", "cm")}
_UNIT_WORDS = {"age": ("years", "year", "yrs", "yr", "months"), "weight": ("kg", "lbs", "lb"),
               "height": ("cm", "inches", "inch", "m")}


def mean_and_range(text: str) -> tuple[float | None, tuple[float, float] | None, str]:
    """A demographic as a synopsis writes it: the stated central value, the range, and the word naming the central value
    ("mean", "median"; "" for a bare number such as "32 ± 8" or "32 (19–45)"). "mean age 32 years (range 19–45)" is
    (32, (19, 45), "mean"); "19 to 45 years" and "between 19 and 45" are (None, (19, 45), ""): no central value is made
    from a range, nor read from an inclusion limit ("18 years or older")."""
    found = _RANGE.search(text)
    low, high = (found.group(1) or found.group(3), found.group(2) or found.group(4)) if found else (None, None)
    span = (float(low), float(high)) if low and high and float(low) < float(high) else None
    rest = text[:found.start()] + " " + text[found.end():] if found and span else text
    word = _CENTRAL.search(rest)
    if word is None and _LIMIT.search(rest):
        return None, span, ""
    after = rest[word.end():] if word else rest
    central = re.search(rf"(?<![\d.]){_NUMBER_TEXT}", after)
    return (float(central.group(0)) if central else None), span, (word.group(1).lower() if word and central else "")


class StatedDemographic:
    """A study's age, weight or height as its files state it (no demographics table): the central value in PK-Sim's unit,
    the range, the status and sources of the fact, and a note with the words as written."""

    def __init__(self, mean: float | None = None, span: tuple[float, float] | None = None, status: str = "missing",
                 sources: tuple[Chip, ...] = (), note: str = ""):
        self.mean, self.span, self.status, self.sources, self.note = mean, span, status, sources, note


def stated_demographic(view: RoomStudy, role: str) -> StatedDemographic:
    """`study.age` / `study.weight` / `study.height` of the study, read with `mean_and_range` in PK-Sim's unit (years,
    kg, cm); a unit the words give that is not one of these is converted (lb, m, months) or, unknown, left Missing."""
    fact = next((v for v in view.facts if v.key.split("[")[0] == f"study.{role}"), None)
    if fact is None:
        return StatedDemographic()
    written = f"{fact.as_written} {fact.unit if fact.unit not in fact.as_written else ''}".strip()
    central, span, word = mean_and_range(fact.as_written)
    unit = fact.unit.strip().lower() or next((u for u in _UNIT_WORDS[role]
                                              if re.search(rf"(?<![a-z]){u}(?![a-z])", fact.as_written.lower())), "")
    unit = "inch" if unit == "inches" else unit
    factor = 1.0 if unit in _PKSIM_UNIT[role] else _UNIT_TO_PKSIM.get((role, unit))
    if factor is None:
        return StatedDemographic(sources=fact.sources, note=f"as written: {written}; its unit {unit!r} is not converted")
    scaled = (round(central * factor, 2) if central is not None else None,
              (round(span[0] * factor, 2), round(span[1] * factor, 2)) if span else None)
    said = f"as written: {written}" + (f" ({word})" if word and word != "mean" else "")
    if scaled[0] is None:
        return StatedDemographic(span=scaled[1], sources=fact.sources, note=(
            f"{said}: no mean is stated" + (f", only the range {scaled[1][0]:g}–{scaled[1][1]:g}" if scaled[1] else "")))
    return StatedDemographic(mean=scaled[0], span=scaled[1], status=fact.status, sources=fact.sources, note=said)


def convention_words(medium: str, ph: float, decision: RoomDecision | None) -> str:
    """How a pH by convention (D4) is labelled wherever it is used: never as the sponsor's."""
    who = decision.by if decision is not None and decision.by else "a person"
    return f"pH {ph:g} by convention for {medium}, not stated (confirmed by {who})"


def _highest(view: DissolutionView) -> float:
    return max((m for m in view.mean if not math.isnan(m)), default=0.0)     # NaN: a time with no unit's value


def release_remark(view: DissolutionView, rules: Rules) -> str:
    """What a Weibull release leaves out of a profile, said beside the release decision and in the evidence sent (the
    behaviour is the SME's to change: the Dissolution register refuses a plateau and sends a very rapid release as
    dissolved); "" when nothing."""
    where = f"{view.medium or 'medium not stated'} · batch {view.batch}"
    if view.plateau:
        return (f"{where} levels off at {_highest(view):.0f} %: a Weibull curve rises to 100 %; the SME decides "
                "(dissolution_similarity / MS-01)")
    if view.very_rapid:
        return (f"{where} releases ≥ {rules.dissolution.very_rapid_percent:g} % within "
                f"{rules.dissolution.very_rapid_within_min:g} min: it is sent as its Weibull fit, where the Dissolution "
                "register would send it as dissolved; the SME decides (dissolution_similarity / MS-01)")
    return ""


def _set_apart(text: str, names: Sequence[str]) -> str | None:
    """The one of `names` whose own words (those no other name has) are all in `text`, and no other name's own words
    are: "clinical formulation, batch QF-C-0921" is "Quorafen 50 mg tablet (clinical formulation)" when the other product
    is "(commercial formulation)". None when no name or two."""
    words = {n: set(_norm(n).split()) for n in names}
    said = set(_norm(text).split())
    own = {n: w - set().union(*(v for m, v in words.items() if m != n)) for n, w in words.items()}
    hits = [n for n in names if own[n] and own[n] <= said]
    return hits[0] if len(hits) == 1 and not any(own[m] & said for m in names if m != hits[0]) else None


def _product_of(code: str, meaning: str, product: str, question: QuestionCard | None,
                batches: Mapping[str, str]) -> tuple[str, str]:
    """An arm's product on the question card, and how it was tied when no document names it (said on the page, the
    owner's choice of 2026-11-24): the product its fact names; the card's only product of the role its meaning names;
    the card's product its words or its batch name; the card's only product."""
    names = [p.name for p in (question.products if question else ())]
    if product:
        return named_in(product, names) or product, ""
    text = f"{code} {meaning}"
    for role in ("reference", "reformulated", "test"):
        if role in meaning.lower():
            of_role = [p.name for p in (question.products if question else ()) if p.role == role]
            if len(of_role) == 1:
                return of_role[0], f"the question card's only {role} product"
    if names and (card := named_in(meaning, names) or _set_apart(text, names)):
        return card, f"the arm's own words name it ({meaning or code})"
    for batch, of in batches.items():
        if batch and f" {batch} " in f" {_norm(text)} ":
            card = named_in(of, names) or of
            return card, f"its batch {batch.upper()} is a batch of {card}"
    if len(names) == 1:
        return names[0], "the question card's only product"
    return "", ""


def _arms(facts: Sequence[CheckedFact], question: QuestionCard | None,
          batches: Mapping[str, str] | None = None) -> list[Arm]:
    """The study's treatment codes and what each stands for: one fact per code (its subject the code), or one sentence
    defining several ("B = test product; A = reference product"). A code's product is the fact's product, else the one
    code ties it to (`_product_of`), which the arm says."""
    out: dict[str, Arm] = {}
    roles = {p.name: p.role for p in (question.products if question else ())}
    for f in facts:
        # a sentence defining several codes ("A = reference; B = test") stands for each, whatever its subject (an agent
        # gave the study's number as the subject of such a sentence, 2026-11-22, and the study became a code)
        defined = _code_pairs(f.fact.value)
        single = bool(f.fact.subject.strip()) and len(defined) < 2
        pairs = [(f.fact.subject.strip(), f.fact.value.strip())] if single else defined
        for code, meaning in pairs:
            product, tied = _product_of(code, meaning, f.fact.product if single else "", question, batches or {})
            out.setdefault(code, Arm(treatment=code, meaning=meaning, product=product, role=roles.get(product, ""),
                                     source=f.chip, tied=tied))
    return sorted(out.values(), key=lambda a: a.treatment)


def _single_arm(view: RoomStudy, question: QuestionCard | None) -> tuple[tuple[Arm, ...], list[Problem]]:
    """The arms of a study whose data name treatments its documents do not define: a single-arm study (one arm, one
    product: a multiple-dose study's days, or a code such as "QD") stands for each of the data's treatments with its one
    product, and says so; a study with no arm defined, on a card with one product, is that product's. A study with one
    arm and no product found asks which of the card's products it used (the new deliveries, 2026-11-24: a single-arm
    study had no product, the wrong role, and N = 0 in the plan)."""
    treatments = sorted({p.treatment for p in view.profiles} | {n.treatment for n in view.nca})
    roles = {p.name: p.role for p in (question.products if question else ())}
    names = list(roles)
    arms = list(view.arms)
    if not treatments or any(a.treatment in treatments for a in arms):
        return tuple(arms), []
    problems: list[Problem] = []
    if len(arms) == 1:
        (arm,) = arms
        how = f"the study's only arm ({arm.meaning or arm.treatment})" + (f"; {arm.tied}" if arm.tied else "")
        if not arm.product and len(names) > 1:
            problems.append(Problem(code="ARM_PRODUCT_UNKNOWN", message=(
                f"study {view.study_id} has one arm ({arm.meaning or arm.treatment}); no document says which of the "
                f"question card's products it used ({', '.join(names)}): name it")))
        return tuple(arm.model_copy(update={"treatment": t, "tied": how}) for t in treatments), problems
    if not arms and len(names) == 1:
        return tuple(Arm(treatment=t, product=names[0], role=roles[names[0]], tied="the question card's only product")
                     for t in treatments), problems
    return tuple(arms), problems


#: a table's constants that are numbers of science (a method's conditions): kept only when the delivery says them
SAID_CONSTANTS = ("medium", "apparatus", "rpm", "speed", "volume", "temperature", "ph")
_CONSTANT_UNITS = {"rpm": ("rpm", "r/min"), "speed": ("rpm", "r/min"), "volume": ("ml", "l"), "temperature": ("°c", "c")}


def _said_constants(tables: Sequence[ReadTable], docs: Iterable[SourceDocument], quotes: Sequence[str]
                    ) -> tuple[list[ReadTable], list[Problem]]:
    """Each table's method conditions as the delivery says them: a constant is kept when its words are written in a
    file, in the table's file name or in a checked quote, and a bare number with its unit ("50 rpm", "pH 6.8"); one
    no file says is left out and said. The agent names the conditions; it may not type them (2026-11-22: "50 rpm" and
    "900 mL" reached f2 from a table's constants that no file stated)."""
    wanted = [t for t in tables if any(k.lower() in SAID_CONSTANTS for k in t.description.constants)]
    if not wanted:
        return list(tables), []
    said = [unmarked(" ".join(ln for _part, lines in document_text(d) for ln in lines)) for d in docs]
    said += [unmarked(q) for q in quotes]
    out, problems = [], []
    for table in tables:
        desc = table.description
        kept, dropped = {}, []
        for key, value in desc.constants.items():
            k, v = key.lower(), unmarked(value)
            if k not in SAID_CONSTANTS or not v:
                kept[key] = value
                continue
            if re.search(r"[a-z]", v):
                phrases = [v]
            elif k == "ph":
                phrases = [f"ph {v}", f"ph{v}"]
            else:
                phrases = [f"{v} {u}" for u in _CONSTANT_UNITS.get(k, ())] + [f"{v}{u}" for u in _CONSTANT_UNITS.get(k, ())]
            pattern = "|".join(rf"(?<![\w.]){re.escape(ph)}(?![\w])" for ph in phrases)
            if pattern and any(re.search(pattern, text) for text in [*said, unmarked(desc.file)]):
                kept[key] = value
            else:
                dropped.append(f"{key} {value!r}")
        if dropped:
            problems.append(Problem(code="CONSTANT_NOT_IN_FILES", message=(
                f"the table on {desc.part} of {desc.file}: {', '.join(dropped)} is written in no file of the delivery, so "
                "it is left out (the agent names a condition; a file must state it)")))
            table = table.model_copy(update={"description": desc.model_copy(update={"constants": kept})})
        out.append(table)
    return out, problems


MEDIA_CONVENTION = "media-ph-convention"


def _media_by_convention(diss: list[DissolutionView], solubility: list[SolubilityRow],
                         made: Mapping[str, Mapping[str, str]]
                         ) -> tuple[list[DissolutionView], list[SolubilityRow], RoomDecision | None]:
    """The decision on media named without a pH (D4), and the profiles and solubility rows with the conventional pH
    applied when, and only when, a person chose to use it: the suggestion alone applies nothing."""
    pending = sorted({(x.medium, x.ph_convention) for x in [*diss, *solubility]
                      if x.ph is None and x.ph_convention is not None})
    if not pending:
        return diss, solubility, None
    named = "; ".join(f"{medium} → pH {ph:g}" for medium, ph in pending)
    decision = _decision(made, RoomDecision(
        id=MEDIA_CONVENTION, title="pH of media named without one",
        question=f"The files name these media without a pH: {named}. Use the pH each has by convention?",
        options=(Option(id="use", label="Use it, labelled \"by convention, not stated\"",
                        detail="f2 pairs, data requests and the reference solubility then use it"),
                 Option(id="leave", label="Leave them without a pH", detail="as the files write them")),
        suggested="use", why="the conventional pH of standard media (dataroom_rules.yaml, UNVERIFIED); the files do "
                             "not state it, so it is confirmed once for the project"))
    if decision.chosen != "use":
        return diss, solubility, decision
    return ([d.model_copy(update={"ph": d.ph_convention, "ph_by_convention": True})
             if d.ph is None and d.ph_convention is not None else d for d in diss],
            [r.model_copy(update={"ph": r.ph_convention, "ph_by_convention": True})
             if r.ph is None and r.ph_convention is not None else r for r in solubility],
            decision)


def _decision(decisions: Mapping[str, Mapping[str, str]], d: RoomDecision) -> RoomDecision:
    made = decisions.get(d.id)
    if made and made.get("chosen") in {o.id for o in d.options}:
        return d.model_copy(update={"chosen": made["chosen"], "reason": made.get("reason", ""), "by": made.get("by", ""),
                                    "at": made.get("at", "")})
    return d


def _pick(d: RoomDecision) -> str:
    return d.chosen or d.suggested


def _first(facts: Sequence[CheckedFact], field: str, subject: str = "") -> CheckedFact | None:
    got = [f for f in facts if f.ok and f.fact.field == field and (not subject or not f.fact.subject
                                                                    or _same_study(f.fact.subject, subject))]
    return got[0] if got else None


# an analyte that is not the drug itself, as files name it: a metabolite, an isotope-labelled tracer ("13C-labeled
# EX-M2", "EX-M1 Exampleamide-Metabolite", "M1")
_NOT_THE_DRUG = re.compile(r"(?i)metabolite|labell?ed|\b13c\b|\b14c\b|deuter|glucuronide|\bm\d{1,2}\b")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def modeled_analyte(named: Sequence[str], facts: Sequence[CheckedFact], question: QuestionCard | None) -> tuple[str, str]:
    """The analyte suggested as the one the model simulates, and why: the one the delivery names as its drug (a
    `study.analyte` fact, the drug substance's or ADME facts' subject, a product of the question card), written in full
    ("Exampleamide") or as its code ("EXAM" begins "exampleamide"); else the first the data lists that is not marked a
    metabolite or a labelled compound. Only a suggestion: the modeler chooses (decision analyte:<study>)."""
    names = [f.fact.value for f in facts if f.ok and f.fact.field == "study.analyte"]
    names += [f.fact.subject for f in facts if f.ok and f.fact.subject and f.fact.field.startswith(("substance.", "adme."))]
    names += [p.name for p in (question.products if question else ())]

    def match(analyte: str) -> tuple[int, str]:
        if _NOT_THE_DRUG.search(analyte):
            return -1, ""
        words, best = _words(analyte), (0, "")
        for name in names:
            theirs = _words(name)
            if words and all(w in theirs for w in words):
                return 2, name
            if any(len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)) for a in words for b in theirs):
                best = max(best, (1, name))
        return best

    (score, name), _i, analyte = max(((match(a), -i, a) for i, a in enumerate(named)), key=lambda x: (x[0][0], x[1]))
    if score > 0:
        return analyte, f"{analyte} is the drug the delivery names ({name})"
    plain = [a for a in named if not _NOT_THE_DRUG.search(a)]
    if plain:
        return plain[0], ("no analyte matches a drug the delivery names: the first the data lists that is not marked a "
                          "metabolite or a labelled compound")
    return named[0], "no analyte matches a drug the delivery names: the first the data lists"


def _analyte_decision(sid: str, named: Sequence[str], tables: Sequence[ReadTable], facts: Sequence[CheckedFact],
                      question: QuestionCard | None) -> RoomDecision:
    counts = {a: sum(len(samples_from(for_analyte(t, a))[0]) for t in tables) for a in named}
    suggested, why = modeled_analyte(named, facts, question)
    first = next((t for t in tables if t.rows), None)
    return RoomDecision(
        id=f"analyte:{sid}", title=f"Modeled analyte for {sid}",
        question=("The study measured more than one analyte. Which one does the model simulate (its profiles are the "
                  "observed data; the others are kept as Supporting Evidence)?"),
        options=tuple(Option(id=a, label=f"{a}: {counts[a]} samples") for a in named), suggested=suggested, why=why,
        evidence=(Chip(file=first.description.file, sha256=first.sha256, part=first.description.part,
                       line=first.description.first_line),) if first else ())


def _of_analyte(tables: Sequence[ReadTable], analyte: str, named: Sequence[str], *, unnamed_too: bool) -> list[ReadTable]:
    """The tables' lines of one analyte of a study that measured several (`named`; with one or none, every table as
    it is); a table that names no analyte at all only when `unnamed_too`."""
    if len(named) < 2:
        return list(tables)
    out = []
    for t in tables:
        if not any(analyte_of(r, t.description) for r in t.rows):
            if unnamed_too:
                out.append(t)
            continue
        if (got := for_analyte(t, analyte)).rows:
            out.append(got)
    return out


def _analyte_view(sid: str, analyte: str, *, named: Sequence[str], concentrations: Sequence[ReadTable],
                  pk_tables: Sequence[ReadTable], facts: Sequence[CheckedFact], arms: Sequence[Arm], release: str,
                  rules: Rules, question: QuestionCard | None, study_values: Sequence[Value] = (),
                  unnamed_pk: bool = False, treatments: Mapping[tuple[str, str], str] | None = None) -> RoomStudy:
    """One analyte of a study, viewed as a study (`study_view`). `unnamed_pk`: a PK table that names no analyte is
    this analyte's (the modeled one's, as before analytes were told apart)."""
    tables = _of_analyte(concentrations, analyte, named, unnamed_too=False)
    view = study_view(sid, concentrations=tables, pk_tables=_of_analyte(pk_tables, analyte, named, unnamed_too=unnamed_pk),
                      facts=facts, arms=arms, study_values=study_values, release=release, rules=rules,
                      treatments=treatments)
    # the tables the profiles are read from: each arm's dataset names them as its source (ICH M15)
    view = view.model_copy(update={"analyte": analyte, "sources": tuple(
        Chip(file=t.description.file, sha256=t.sha256, part=t.description.part, line=t.description.first_line)
        for t in tables)})
    tied, asked = _single_arm(view, question)
    if tied != view.arms:
        # a single arm tied to every treatment of the data no longer asks which treatment it is
        kept = tuple(x for x in view.problems if x.code != "ARM_MATCHES_NO_TREATMENT" or len(view.arms) != 1)
        view = view.model_copy(update={"arms": tied, "problems": kept + tuple(asked)})
    return view


def read_extractions(inputs: Inputs) -> tuple[list[ReadTable], list[CheckedFact], list[Problem]]:
    """Every described table read and every quoted fact checked against the read documents, each table's method
    conditions kept as the delivery says them: the room's first step (`assemble`), and what the value scorer reads
    (`modeler_project.value_score.from_dataroom`), so both see the same values."""
    by_path = {f.path: f for f in inputs.files}
    problems: list[Problem] = []
    tables: list[ReadTable] = []
    facts: list[CheckedFact] = []
    for ext in inputs.extractions:
        for table in ext.tables:
            path = table.file or ext.file
            file = by_path.get(path)
            doc = inputs.docs.get(file.sha256) if file else None
            if doc is None:
                problems.append(Problem(code="FILE_NOT_READ", severity="error", message=f"{path}: no read document"))
                continue
            got = read_table(table.model_copy(update={"file": path}), doc, file=path, sha256=file.sha256)
            tables.append(got)
            problems += got.problems
        for fact in ext.facts:
            path = fact.file or ext.file
            file = by_path.get(path)
            doc = inputs.docs.get(file.sha256) if file else None
            if doc is None:
                facts.append(CheckedFact(fact=fact, ok=False, problem=f"{path}: no read document"))
                continue
            facts.append(check_fact(fact.model_copy(update={"file": path}), doc, file=path, sha256=file.sha256))
    tables, found = _said_constants(tables, inputs.docs.values(), [f.fact.quote for f in facts if f.ok])
    return tables, facts, problems + found


def assemble(inputs: Inputs, *, rules: Rules | None = None) -> DataRoomView:
    rules = rules or load_rules()
    triage = {f.path: f.triage for f in inputs.files if f.triage}
    literature_files = {p for p, t in triage.items() if t and set(t.topics) & _LITERATURE_TOPICS}
    tables, facts, problems = read_extractions(inputs)
    for f in facts:
        if not f.ok:
            problems.append(Problem(code="FACT_REFUSED", message=f"{_field_label(f.fact.field)} “{f.fact.value}” ({f.fact.file}): "
                                    f"{f.problem}"))
    for path, issues in inputs.reviews.items():
        for issue in issues:
            problems.append(Problem(code="CHECKER_ISSUE", message=f"{path}, table {issue.get('table', '?')}: {issue.get('issue', '')}"))
    by_kind: dict[str, list[ReadTable]] = defaultdict(list)
    for t in tables:
        by_kind[t.description.kind].append(t)
    question = inputs.question
    roles = {p.name: p.role for p in (question.products if question else ())}

    # --- values: drug substance, ADME, products -------------------------------------------------------------------
    from modeler_intake.room_specs import FIELDS
    substance = _values(facts, "substance.", FIELDS, literature_files, rules)
    # permeability: the lab's reference compounds apart from the drug's own value, a fitted value labelled so (plan
    # 2026-11-24 §8 feature 6)
    substance, own_permeability, reference_compounds = _permeability(
        substance, rules, [p.name for p in (inputs.question.products if inputs.question else ())])
    adme = _values(facts, "adme.", FIELDS, literature_files, rules)
    products = _values(facts, "product.", FIELDS, literature_files, rules) + _values(facts, "batch.", FIELDS, literature_files, rules)
    entered = {v.key: v for v in inputs.entered}

    # the dose in both bases (R14): PK-Sim's compound is the free base, so a salt dose is given as the base's
    dose_info, found = dose_card(facts)
    problems += found
    # checks across the delivery (R03 simulated data, R07 lots, a file about another drug, personal data)
    drug_names = [f.fact.subject for f in facts if f.ok and f.fact.subject and f.fact.field.startswith(("substance.", "adme."))]
    drug_names += [f.fact.value for f in facts if f.ok and f.fact.field == "study.analyte"]
    drug_names += [p.name for p in (question.products if question else ())]
    problems += detect(files=inputs.files, docs=inputs.docs, tables=tables, facts=facts, drug_names=drug_names)

    # --- clinical ---------------------------------------------------------------------------------------------------
    study_ids: list[str] = []
    for t in by_kind["concentrations"]:
        sid = t.description.about or t.description.constants.get("study", "") or "study"
        if not any(_same_study(sid, s) for s in study_ids):
            study_ids.append(sid)
    studies: list[RoomStudy] = []
    other_analytes: list[RoomStudy] = []
    decisions: list[RoomDecision] = []
    # the products' release as the files write it (the vomiting rule is for immediate release)
    release = "; ".join(dict.fromkeys(f.fact.value for f in facts if f.ok and f.fact.field == "product.release"))
    for sid in study_ids:
        def mine(kind: str, sid: str = sid) -> list[ReadTable]:
            return [t for t in by_kind[kind] if not t.description.about or _same_study(t.description.about, sid)
                    or len(study_ids) == 1]

        sfacts = [f for f in facts if f.fact.field.startswith("study.") and (not f.fact.subject or len(study_ids) == 1
                                                                              or _same_study(f.fact.subject, sid))]
        arms = _arms([f for f in sfacts if f.ok and f.fact.field == "study.treatment_code"], question, batch_products(facts))
        study_values = _values([f for f in sfacts if f.fact.field != "study.treatment_code"], "study.", FIELDS,
                               literature_files, rules)
        # a study that measured several analytes (the drug and its metabolites, line by line in a CRO's PC dataset) is
        # viewed once per analyte: the modeler chooses the one the model simulates; the others are Supporting Evidence
        conc, pk = mine("concentrations"), mine("pk_parameters")
        named = analytes_in(conc)
        modeled = named[0] if named else ""
        if len(named) > 1:
            choice = _decision(inputs.decisions, _analyte_decision(sid, named, conc, facts, question))
            decisions.append(choice)
            modeled = _pick(choice)
            if unnamed := sum(unnamed_lines(t) for t in conc):
                problems.append(Problem(code="ANALYTE_NOT_NAMED", severity="error", message=(
                    f"{sid}: {unnamed} concentration line{'s' if unnamed > 1 else ''} name no analyte, while the study "
                    f"measured {len(named)} ({', '.join(named)}): left out of every analyte's profiles; say which "
                    "analyte they are (an analyte column, or the table's analyte)")))

        known = {a.lower() for a in named}
        if named and (strays := [a for a in analytes_in(pk) if a.lower() not in known]):
            problems.append(Problem(code="PK_ANALYTE_NOT_IN_DATA", message=(
                f"{sid}: the client's PK values of {', '.join(strays)} name no analyte of the concentration data "
                f"({', '.join(named)}): they are not compared with ours")))
        # what each subject was given on each occasion (an EX dataset): the profiles' treatments when the concentration
        # data name none; whether two doses of one product make two arms is the modeler's choice
        dosing = mine("dosing")
        treatments: dict[tuple[str, str], str] = {}
        if dosing:
            several, suggested, why = dose_arms(dosing)
            per_dose = True
            if several:
                choice = _decision(inputs.decisions, RoomDecision(
                    id=f"dose-arms:{sid}", title=f"Dose groups of {sid}",
                    question=("A product was given at more than one dose. Is each dose its own arm (the design's dose "
                              "levels), or one arm per product with each subject's own dose (individualised dosing)?"),
                    options=(Option(id="per_dose", label="One arm per dose"),
                             Option(id="one_arm", label="One arm per product, each subject's own dose")),
                    suggested=suggested, why=why, evidence=tuple(
                        Chip(file=t.description.file, sha256=t.sha256, part=t.description.part,
                             line=t.description.first_line) for t in dosing[:1])))
                decisions.append(choice)
                per_dose = _pick(choice) == "per_dose"
            treatments = assignments(dosing, per_dose=per_dose)
        view = _analyte_view(sid, modeled, named=named, concentrations=conc, pk_tables=pk, facts=sfacts, arms=arms,
                             study_values=study_values, release=release, rules=rules, question=question,
                             unnamed_pk=True, treatments=treatments)
        other_analytes += [_analyte_view(sid, a, named=named, concentrations=conc, pk_tables=pk, facts=sfacts, arms=arms,
                                         release=release, rules=rules, question=question, treatments=treatments)
                           for a in named if a != modeled]
        sets = {s.name: s for s in view.sets}
        options = [Option(id=name, label=f"{sets[name].label}: {len(sets[name].subjects)} subjects", detail=sets[name].rule)
                   for name in ("modeling", "client_statistical", "completed", "dosed") if name in sets]
        if options:
            decisions.append(_decision(inputs.decisions, RoomDecision(
                id=f"analysis-set:{sid}", title=f"Analysis set for {sid}'s observed profiles",
                question="Which subjects make the observed mean profiles the model is compared with?", options=tuple(options),
                suggested="modeling", why="; ".join(f"subject {s}: {r}" for s, r in sorted(
                    view.excluded.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0) if "LLOQ" in r) or
                "the completers with evaluable profiles in every period")))
        # the study's bioequivalence computed by code on the chosen set, beside the CSR's (plan 2026-11-26 phase 3)
        chosen_set = _pick(decisions[-1]) if options else "modeling"
        be, found = be_results(view, set_name=chosen_set, csr=csr_values(mine("be_statistics")), rules=rules)
        view = view.model_copy(update={"be": be, "problems": view.problems + tuple(found)})
        dem = _demographics(mine("demographics"), sets["modeling"].subjects if "modeling" in sets else ())
        ethnicity = _first(sfacts, "study.ethnicity")
        guess = (population_of(ethnicity.fact.value) if ethnicity else None) or "European_ICRP_2002"
        decisions.append(_decision(inputs.decisions, RoomDecision(
            id=f"population:{sid}", title=f"Population for {sid}",
            question="Which PK-Sim population database stands for the study's subjects?",
            options=tuple(Option(id=p, label=POPULATION_LABELS[p]) for p in POPULATIONS), suggested=guess,
            why=(f"the study's subjects are {ethnicity.fact.value}" if ethnicity else "no ethnicity found: the reference European")
            + ("; no Indian population exists in PK-Sim yet (backlog): the Asian database is the closest" if ethnicity and
               "indian" in ethnicity.fact.value.lower() else ""), evidence=(ethnicity.chip,) if ethnicity and ethnicity.chip else ())))
        sex_fact = _first(sfacts, "study.sex")
        males, females = int(dem.get("male", 0) or 0), int(dem.get("female", 0) or 0)
        stated = sex_of(sex_fact.fact.value) if sex_fact else None
        if (males and females) or stated == "MIXED":
            decisions.append(_decision(inputs.decisions, RoomDecision(
                id=f"sex:{sid}", title=f"Sex of {sid}'s individual",
                question="The study has men and women; a PK-Sim individual is one sex. Which stands for the study?",
                options=(Option(id="MALE", label="Male"), Option(id="FEMALE", label="Female")),
                suggested="FEMALE" if females > males else "MALE",
                why=f"{males} men and {females} women in the modeling set" if males or females else sex_fact.fact.value,
                evidence=(sex_fact.chip,) if sex_fact and sex_fact.chip else ())))
        meal = _first(sfacts, "study.meal_composition") or _first(sfacts, "study.fed") or _first(sfacts, "study.meal_times")
        if meal:
            high_fat = "high" in meal.fact.value.lower() and "fat" in meal.fact.value.lower()
            decisions.append(_decision(inputs.decisions, RoomDecision(
                id=f"meal:{sid}", title=f"Meal template for {sid}",
                question="Which PK-Sim meal stands for the study's meals?",
                options=(Option(id="standard", label="Standard meal"), Option(id="high_fat", label="High-fat breakfast")),
                suggested="high_fat" if high_fat else "standard",
                why=("the composition says high-fat" if high_fat else
                     "the meal's composition is not given: the standard meal, until the client confirms it"),
                evidence=(meal.chip,) if meal.chip else ())))
        studies.append(view.model_copy(update={"facts": view.facts + tuple(
            Value(key=f"study.{sid}.demographics.{k}", label=k.replace("_", " "), value=v, status="calculated",
                  rule="over the proposed modeling set" if "modeling" in sets else "over every subject")
            for k, v in dem.items() if k != "n")}))

    # --- in vitro ---------------------------------------------------------------------------------------------------
    batches = batch_products(facts)
    diss: list[DissolutionView] = []
    for t in by_kind["dissolution"]:
        views, found = dissolution_views(t, products=batches, rules=rules)
        diss += views
        problems += found
    # each profile's product as the question card names it ("Tablet, Lot NP-R-2201" and "…, batch ZT-R-118" were no
    # product of the card: no role, no f2, and nothing said); one still unnamed is said
    if roles:
        named = []
        for d in diss:
            card = named_in(d.product, roles) if d.product else None
            if card and card != d.product:
                d = d.model_copy(update={"product": card})
            elif not card:
                problems.append(Problem(code="PROFILE_PRODUCT_UNKNOWN", message=(
                    f"dissolution of {d.batch or d.product or 'a batch'} in {d.medium or 'its medium'}: its product "
                    f"{'(' + d.product + ') ' if d.product else ''}is none of the question card's "
                    f"({', '.join(roles)}): no role, so no f2 with it; name the batch's product")))
            named.append(d)
        diss = named
    composition = composition_rows(by_kind["composition"], rules)
    strength = _first(facts, "product.strength") or _first(facts, "study.dose")
    dose = strength.number if strength else None
    doses = _doses(facts, question, strength)
    medium_volume = next((d.volume_ml for d in diss if d.volume_ml), None)
    solubility, found = solubility_rows(by_kind["solubility"], dose_mg=dose, medium_volume_ml=medium_volume, rules=rules)
    problems += found
    solubility += solubility_from_facts([f for f in facts if f.ok and f.fact.field == "substance.solubility"], dose_mg=dose,
                                        medium_volume_ml=medium_volume, rules=rules)
    # a medium named without its pH ("0.1 N HCl"): its pH by convention, labelled so, used only once a person confirms
    # it for the project (the owner, 2026-11-24, D4); until then the medium stays without a pH, as written
    diss, solubility, convention = _media_by_convention(diss, solubility, inputs.decisions)
    if convention is not None:
        decisions.append(convention)
    # the science checks across a section (plan 2026-11-24 §8 features 7-9): the batches of a product tested by
    # different methods; a functional excipient that differs between test and reference; which step may limit
    # absorption (the dose number per medium, the sink index of each dissolution medium)
    checks: dict[str, tuple[Problem, ...]] = {}
    if found_methods := method_checks(diss):
        checks["dissolution"] = tuple(found_methods)
    if found_excipients := excipient_checks(composition, roles):
        checks["formulation"] = tuple(found_excipients)
    absorption = limiting_steps(solubility, [(", ".join(products), mg, written, chips)
                                             for (mg, written, chips), products in _by_dose(doses).items()], rules)
    dose_of = {product: mg for product, mg, _w, _c in doses}
    sinks = []
    for d in diss:
        value, basis, low = sink_index(d, solubility, dose_of.get(d.product, dose), rules)
        sinks.append(d.model_copy(update={"sink_index": value, "sink_basis": basis,
                                          "problems": d.problems + ((low,) if low else ())}))
    diss = sinks
    f2s = f2_pairs(diss, roles)
    for product in sorted({d.product or d.batch for d in diss}):
        views = [d for d in diss if (d.product or d.batch) == product]
        qc = next((d for d in views if "qc" in d.medium.lower()), None)
        # a profile a Weibull curve does not describe (it levels off below 100 %, or is very rapid) is still offered and
        # sent as its Weibull fit (SME-gated: the Dissolution register refuses the one and sends the other as dissolved);
        # the decision says so beside it
        remarks = [r for d in views if (r := release_remark(d, rules))]
        decisions.append(_decision(inputs.decisions, RoomDecision(
            id=f"release:{product}", title=f"Release of {product}",
            question="Which dissolution profile gives the product's release in the model (a Weibull fit to it)?",
            options=tuple(Option(id=d.id, label=f"{d.medium or 'medium not stated'} · batch {d.batch}",
                                 detail=f"t50 {d.weibull.get('t50_min')} min, shape {d.weibull.get('shape')}"
                                 + (f" · levels off at {_highest(d):.0f} %" if d.plateau else "")
                                 + (" · very rapid" if d.very_rapid else "")) for d in views),
            suggested=(qc or views[0]).id,
            why=("the medium the client uses for quality control" if qc else "the first profile; compare the media")
            + "".join(f". {r}" for r in remarks),
            evidence=tuple(c for d in views for c in d.sources[:1]))))

    if solubility:
        water = next((r for r in solubility if "water" in r.medium.lower()), None)
        decisions.append(_decision(inputs.decisions, RoomDecision(
            id="solubility-ref", title="Reference solubility",
            question="Which measured solubility is the compound's reference solubility (PK-Sim scales it with pH from the pKa)?",
            options=tuple(Option(id=f"sol-{i}", label=f"{r.as_written} in {r.medium}" + (f" (pH {r.ph:g})" if r.ph is not None else ""))
                          for i, r in enumerate(solubility)),
            suggested=f"sol-{solubility.index(water) if water else 0}",
            why="the solubility in water" if water else "the first measured medium; compare with the pKa",
            evidence=tuple(r.sources[0] for r in solubility if r.sources)[:3])))
    chosen = {d.id: _pick(d) for d in decisions}
    for product in sorted({d.product or d.batch for d in diss}):
        view = next((d for d in diss if d.id == chosen.get(f"release:{product}")), None)
        if view is not None and view.plateau:
            decisions.append(_decision(inputs.decisions, RoomDecision(
                id=f"release-model:{product}", title=f"Release model for {product}",
                question="The chosen profile levels off below 100 %. How should the model release the drug?",
                options=(Option(id="weibull", label="Weibull fitted to the profile as measured",
                                detail=f"t50 {view.weibull.get('t50_min')} min, shape {view.weibull.get('shape')}: it creeps "
                                "towards 100 % after the last time"),
                         Option(id="particles", label="Particle dissolution from the particle size and the solubility",
                                detail="the plateau is then the solubility limit in the medium; needs d50 and solubility vs pH")),
                suggested="weibull", why=f"the highest mean is {_highest(view):.0f} % at {view.times_min[-1]:g} min. "
                f"{release_remark(view, rules)}", evidence=view.sources[:1])))
    chosen = {d.id: _pick(d) for d in decisions}

    # --- what the question needs (plan 2026-11-24 §6): the requirement drafts per context of use, UNVERIFIED -----------
    # the applications read from the question card (a decision, first), then each item of their lists with its coverage
    applications = checklist.applications_decision(question, inputs.decisions)
    if applications is not None:
        decisions.insert(0, applications)
    cell_assay = [v for v in own_permeability
                  if _CELL_ASSAY.search(" ".join([v.as_written, v.unit] + [c.text for c in v.sources]))]
    evidence = checklist.Evidence(
        facts=facts, tables=tables, files=inputs.files, solubility=solubility,
        pkas=checklist.pka_values(facts, pka_type),
        cell_permeability=cell_assay, entered={field: entered[key] for key, _l, field, _u in COMPOUND if key in entered},
        arm_food=[(food, a.source) for s in studies for a in s.arms if (food := food_of(a.meaning))])
    needs = checklist.requirements(question, applications, evidence)
    # the question card's checklist items that ask only for context-only material (the manufacturing process): kept as
    # context, their request marked not needed (a person may open it again)
    context_items = checklist.context_checklist(question)

    # --- data requests -------------------------------------------------------------------------------------------------
    requests: list[DataRequest] = []

    def request(area: str, title: str, why: str, checklist: str = "", input: str = "", status: str = "open") -> None:
        n = sum(1 for r in requests if r.area == area) + 1
        rid = f"{area}-{n:02d}"
        edit = inputs.request_edits.get(rid, {})
        wording = edit.get("wording") or inputs.writing.get("requests", {}).get(title, "")
        requests.append(DataRequest(id=rid, area=area, title=title, why=why, wording=wording,  # type: ignore[arg-type]
                                    status=edit.get("status", status), checklist=checklist, input=input))  # type: ignore[arg-type]

    covered_topics: set[str] = set()
    for topic, prefixes in _TOPIC_FIELDS.items():
        if any(f.ok and f.fact.field.startswith(prefixes) for f in facts):
            covered_topics.add(topic)
    for topic, kinds in _TOPIC_TABLES.items():
        if any(by_kind[k] for k in kinds):
            covered_topics.add(topic)
    if question and inputs.question_confirmed:
        for item in question.checklist:
            if item.required and item.topics and not set(item.topics) & covered_topics:
                if (ctx := context_items.get(item.id)) is not None:
                    request(item.area, item.label, f"Kept as context, not asked for: {ctx.why.rstrip('.')}. "
                            f"{checklist.DRAFT_WORDS}", item.id, status="not_needed")
                    continue
                request(item.area, item.label, item.why or "needed for the question and not found in the delivery", item.id)
    for view in studies:
        for s, why in view.excluded.items():
            if "LLOQ" in why:
                request("D", f"Subject {s} of {view.study_id}: every concentration below the LLOQ",
                        "confirm the dose was taken and the samples assayed; until then the subject is out of the modeling set")
        for p in view.problems:
            if p.code in ("DOSED_DIFFERS", "COMPLETERS_DIFFER"):
                request("D", f"{view.study_id}: subject counts", p.message)
        # the client's values no NCA setting reproduces (plan 2026-11-24 §8 feature 3): the data differ, or one setting
        # of the client's analysis plan is not among those tried
        rep = view.nca_reproduction
        if rep is not None and rep.differ:
            request("D", f"{view.study_id}: the client's values the data do not reproduce", (
                f"{rep.differ} of the client's NCA values {'differs' if rep.differ == 1 else 'differ'} by more than "
                f"{rules.nca.reproduce.investigate_percent:g} % "
                "under every NCA setting tried: were samples re-assayed, excluded or re-timed, or the values transcribed?"))
        if rep is not None and rep.investigate:
            request("D", f"{view.study_id}: the client's NCA settings", (
                f"{rep.investigate} of the client's NCA values {'differs' if rep.investigate == 1 else 'differ'} by "
                f"{rules.nca.reproduce.pass_percent:g}–{rules.nca.reproduce.investigate_percent:g} % (or only another "
                "setting reproduces it for one profile): "
                "the analysis plan's integration rule, time basis, BLQ rule and λz window would say which setting differs"))
    for d in diss:
        for p in d.problems:
            if p.code in ("MEAN_ROW_DIFFERS", "RSD_ROW_DIFFERS"):
                request("B", f"Dissolution {d.batch} in {d.medium}: the summary row", p.message)
    written = {(d.ph, _norm(d.medium)): d.medium for d in diss}
    tested = {(d.ph, _norm(d.medium)) for d in diss if roles.get(d.product) not in ("reference", None, "")}
    with_ref = {(d.ph, _norm(d.medium)) for d in diss if roles.get(d.product) == "reference"}
    for ph, medium in sorted(tested - with_ref, key=lambda x: (x[0] or 0, x[1])):
        if roles and any(r == "reference" for r in roles.values()):
            where = written.get((ph, medium)) or (f"pH {ph:g}" if ph is not None else "the medium the test product was run in")
            request("B", f"Reference product dissolution in {where}",
                    "the test product was tested in this medium and the reference was not: no comparison is possible")
    if cell_assay and not reference_compounds:
        request("C", "The lab's reference compounds for the permeability assay", (
            f"the delivery gives {len(cell_assay)} cell-assay permeabilit{'y' if len(cell_assay) == 1 else 'ies'} "
            f"({cell_assay[0].as_written} {cell_assay[0].unit}".rstrip() + ") but not the lab's reference compounds "
            "measured in the same assay (for example metoprolol, atenolol): an apparent permeability is on another "
            "scale than PK-Sim's intestinal permeability (about 100 ×), and each lab needs its own calibration, so "
            "without them the value stays evidence"), "substance.permeability")
    for key, label, field, _unit in COMPOUND:
        word = label.split(" (")[0].lower()
        asked = any(word in r.title.lower() or field in r.checklist for r in requests)
        found = (bool(own_permeability) if key == "perm.intestinal" else any(v.key.startswith(field) for v in substance + adme)
                 or (key == "phys.solubility.ref" and bool(solubility)))
        if not found and key not in entered and not asked:
            request("C", label, "a compound input of the model, not in the delivery: from the client, or from literature (marked so)",
                    field, input=key)
    # the checklist's missing items, after the room's own requests (their codes stay as they were): what, why, the
    # accepted alternatives, "(draft requirement, UNVERIFIED)"; one the room already makes is not made twice. Nothing
    # not needed, inapplicable, not known, optional or context-only is asked for.
    if needs is not None:
        asked_in: dict[str, str] = {}
        if question and inputs.question_confirmed:
            for ask in checklist.asks(needs.items):
                same = checklist.already_asked(ask, requests)
                if same is None:
                    request(ask.area, ask.title, ask.why, ask.item)
                    same = requests[-1]
                asked_in[ask.item] = same.id
        for cid, ctx in context_items.items():
            if got := next((r for r in requests if r.checklist == cid), None):
                asked_in.setdefault(ctx.id, got.id)
        needs = needs.model_copy(update={"items": tuple(
            i.model_copy(update={"request": asked_in[i.id]}) if i.id in asked_in else i for i in needs.items)})

    # --- PK-Sim inputs ---------------------------------------------------------------------------------------------------
    inputs_rows: list[InputRow] = []
    pka_rows = _pka_rows([f for f in facts if f.ok and f.fact.field == "substance.pka"], substance)
    for key, name, field, unit in COMPOUND:
        if key in entered:
            v = entered[key]
            inputs_rows.append(InputRow(block="compound", name=key, label=name, value=v.value, unit=v.unit, status="entered",
                                        note=v.note))
            continue
        if key == "phys.pka.base.0":
            inputs_rows += pka_rows or [InputRow(block="compound", name=key, label=name, status="missing",
                                                 note="not in the delivery: literature or a data request")]
            continue
        if key == "phys.solubility.ref":
            if solubility and chosen.get("solubility-ref"):
                row = solubility[int(chosen["solubility-ref"].split("-")[1])]
                inputs_rows.append(InputRow(block="compound", name=key, label=label_of(key), value=row.solubility_mg_ml,
                                            unit="mg/ml", status="sponsor" if row.solubility_mg_ml is not None else "missing",
                                            sources=row.sources, decision="solubility-ref", note=row.as_written))
                # a pH by convention (D4) is not the sponsor's: the files do not state it, a person confirmed the convention
                ph_status = "missing" if row.ph is None else ("calculated" if row.ph_by_convention else "sponsor")
                inputs_rows.append(InputRow(block="compound", name="phys.solubility.ref_ph", label="Reference pH", value=row.ph,
                                            status=ph_status, sources=row.sources,  # type: ignore[arg-type]
                                            decision=MEDIA_CONVENTION if row.ph_by_convention else "solubility-ref",
                                            note="the chosen solubility states no pH" if row.ph is None else
                                            convention_words(row.medium, row.ph, convention) if row.ph_by_convention else ""))
            else:
                inputs_rows.append(InputRow(block="compound", name=key, label=name, unit=unit, status="missing",
                                            note="not in the delivery: literature or a data request"))
            continue
        got = (own_permeability[0] if own_permeability else None) if key == "perm.intestinal" else next(
            (v for v in substance + adme if v.key.split("[")[0] == field), None)
        if got is None:
            inputs_rows.append(InputRow(block="compound", name=key, label=name, unit=unit, status="missing",
                                        note="not in the delivery: literature or a data request"))
            continue
        value, row_unit, note, status = got.value, got.unit, "", got.status
        if not isinstance(value, float):
            value, status, note = None, "missing", f"not one number as written ({got.as_written!r}): enter the value"
        elif key == "bind.fu":
            # bound or unbound by the file's own words only: the agent's note once said "fraction unbound = 3%" beside
            # "Plasma protein binding: 97 %", and fu came out 0.97 instead of 0.03 (Nemotron, 2026-11-22)
            quote = " ".join([got.as_written] + [c.text for c in got.sources])
            value, note = fraction_unbound(value, got.unit, quote)
            row_unit = ""
            if value is None:
                status = "missing"
        origin, label = "", name
        if key == "perm.intestinal" and isinstance(got.value, float):
            # a cell assay's apparent permeability (Caco-2, MDCK, PAMPA; cm/s) is not PK-Sim's specific intestinal
            # permeability (cm/min): it went straight in, status sponsor, with no conversion (a new delivery, 2026-11-24)
            quote = " ".join([got.as_written, got.unit] + [c.text for c in got.sources])
            if _FITTED.search(quote):
                # a value the files state was fitted to clinical PK: labelled fitted, never measured (feature 6)
                origin, label = "fitted", f"{name}, fitted"
                note = "the files state it was fitted to clinical PK: a fitted value, not a measurement"
            if _CELL_ASSAY.search(quote) or got.unit.replace(" ", "").lower() != "cm/min":
                value, status = None, "missing"
                calibration = "; ".join(f"{v.key.split('[', 1)[-1].rstrip(']')} {v.as_written} {v.unit}".strip()
                                        for v in reference_compounds)
                note = (f"{got.as_written} {got.unit}".strip() + ": a cell assay's apparent permeability, not PK-Sim's "
                        "specific intestinal permeability (cm/min). It needs a calibration against reference drugs, or "
                        "PK-Sim's own estimate from lipophilicity; kept as evidence, not sent" +
                        (f". The lab's reference compounds are in the delivery ({calibration}): evidence for that "
                         "calibration, not applied" if calibration else
                         ". The lab's reference compounds are not in the delivery: a data request asks for them"))
        inputs_rows.append(InputRow(block="compound", name=key, label=label, value=value, unit=row_unit, status=status,
                                    sources=got.sources, note=note, origin=origin))
    for product in sorted({d.product or d.batch for d in diss}):
        did = chosen.get(f"release:{product}")
        view = next((d for d in diss if d.id == did), None)
        if view is None:
            continue
        inputs_rows.append(InputRow(block="formulation", owner=product, name="Formulation_Tablet_Weibull",
                                    label="Formulation type", value="Formulation_Tablet_Weibull", status="calculated",
                                    decision=f"release:{product}"))
        for k, v, unit in (("t50", view.weibull.get("t50_min"), "min"), ("shape", view.weibull.get("shape"), ""),
                           ("lag", view.weibull.get("lag_min"), "min")):
            inputs_rows.append(InputRow(block="formulation", owner=product, name=WEIBULL_PARAMETERS[k], label=WEIBULL_PARAMETERS[k],
                                        value=v, unit=unit, status="calculated", sources=view.sources[:1],
                                        decision=f"release:{product}",
                                        note=f"Weibull fit to {view.medium} · batch {view.batch}, RMSE "
                                        f"{view.weibull.get('rmse_percent')} %" + (" (the profile levels off below 100 %)"
                                                                                  if view.plateau else "")))
    plan: list[PlanRow] = []
    for view in studies:
        sid = view.study_id
        sets = {s.name: s for s in view.sets}
        set_name = chosen.get(f"analysis-set:{sid}", "modeling")
        population = chosen.get(f"population:{sid}", "European_ICRP_2002")
        inputs_rows.append(InputRow(block="individual", owner=sid, name="Population", label="Population database",
                                    value=population, status="calculated", decision=f"population:{sid}"))
        dem = {v.key.rsplit(".", 1)[-1]: v for v in view.facts if ".demographics." in v.key}
        stated: dict[str, float] = {}
        for k, label, unit in (("age_mean", "Age", "year(s)"), ("weight_mean", "Weight", "kg"), ("height_mean", "Height", "cm")):
            if k in dem:
                inputs_rows.append(InputRow(block="individual", owner=sid, name=label, label=f"{label} (mean)",
                                            value=dem[k].value, unit=unit, status="calculated", note=dem[k].rule))
                continue
            # no demographics table (or no such column): the synopsis's own words ("mean age 32 years (range 19–45)"),
            # their mean as written; a range alone gives no mean (none is made up)
            got = stated_demographic(view, k.split("_")[0])
            if got.mean is not None:
                stated[k] = got.mean
                inputs_rows.append(InputRow(block="individual", owner=sid, name=label, label=f"{label} (mean)",
                                            value=got.mean, unit=unit, status=got.status,  # type: ignore[arg-type]
                                            sources=got.sources, note=got.note))
            else:
                inputs_rows.append(InputRow(block="individual", owner=sid, name=label, label=f"{label} (mean)", unit=unit,
                                            status="missing", sources=got.sources,
                                            note=got.note or "no demographics table read, and no file states it"))
        sex = next((v for v in view.facts if v.key.startswith("study.sex")), None)
        males = next((v.value for v in view.facts if v.key.endswith(".demographics.male")), 0) or 0
        females = next((v.value for v in view.facts if v.key.endswith(".demographics.female")), 0) or 0
        gender = chosen.get(f"sex:{sid}") or ("FEMALE" if females and not males else "MALE" if males and not females else
                                              (sex_of(sex.as_written) if sex else None))
        gender = None if gender == "MIXED" else gender
        inputs_rows.append(InputRow(block="individual", owner=sid, name="Gender", label="Sex", value=gender,
                                    status=("calculated" if (males or females) else sex.status if sex else "missing")
                                    if gender else "missing", sources=sex.sources if sex else (),
                                    decision=f"sex:{sid}" if f"sex:{sid}" in chosen else "",
                                    note="" if gender else "the study's sex is not stated"))
        fed = next((v for v in view.facts if v.key.startswith("study.fed")), None)
        fasting = next((v for v in view.facts if v.key.startswith("study.fasting")), None)
        food = "fed" if fed else ("fasted" if fasting else None)
        # each arm's own words first ("tablet, fed"; "after a high-fat breakfast"): a food-effect study's fasted arms
        # showed "fed" from the study's one statement (a new delivery, 2026-11-24). An arm that says neither takes the
        # study's statement: one arm "after a high-fat breakfast" beside an arm that says nothing, in a study "after an
        # overnight fast", is a fed arm and a fasted one (both were sent fasted before)
        arm_food = {a.treatment: f for a in view.arms if (f := food_of(a.meaning))}
        food_of_arm = {a.treatment: arm_food.get(a.treatment) or food for a in view.arms}
        if len(set(food_of_arm.values())) > 1:
            for a in view.arms:
                own = arm_food.get(a.treatment)
                inputs_rows.append(InputRow(block="protocol", owner=f"{sid} · {a.treatment}", name="Food state",
                                            label="Fed or fasted", value=own or food,
                                            status=("sponsor" if own else (fed or fasting).status  # type: ignore[union-attr]
                                                    if food else "missing"),
                                            sources=((a.source,) if a.source else ()) if own else
                                            (fed or fasting).sources if food else (),  # type: ignore[union-attr]
                                            note="" if own else "the study's own statement: the arm does not say" if food
                                            else "the arm does not say fed or fasted"))
        elif arm_food and len(arm_food) == len(view.arms):
            # every arm says the same: the arms' own words (they name the condition each was dosed in)
            said = next(a for a in view.arms if a.treatment in arm_food)
            inputs_rows.append(InputRow(block="protocol", owner=sid, name="Food state", label="Fed or fasted",
                                        value=arm_food[said.treatment], status="sponsor",
                                        sources=tuple(a.source for a in view.arms if a.source), note="as each arm says"))
        else:
            inputs_rows.append(InputRow(block="protocol", owner=sid, name="Food state", label="Fed or fasted", value=food,
                                        status=(fed or fasting).status if food else "missing",  # type: ignore[union-attr]
                                        sources=(fed or fasting).sources if food else (),  # type: ignore[union-attr]
                                        note="" if food else "the study does not say fed or fasted"))
        dose_v = next((v for v in view.facts if v.key.startswith("study.dose")), None)
        water = next((v for v in view.facts if v.key.startswith("study.water")), None)
        # the mean weight the water is divided by: the demographics table's, else the one the files state
        weight: tuple[float, str] | None = None
        if "weight_mean" in dem and isinstance(dem["weight_mean"].value, float):
            weight = (dem["weight_mean"].value, "the mean weight")
        elif "weight_mean" in stated:
            weight = (stated["weight_mean"], "the stated mean weight")
        # a multiple-dose study's occasions are its days, not arms
        occasion = "day" if any(x.code == "MULTIPLE_DOSE" for x in view.problems) else "arm"
        # in a food-effect question the fed arms are what the model predicts: never fitted (MS-01 §3.3 rule 5)
        food_effect = any(a.id == "food_effect" for a in checklist.chosen_applications(applications))
        for arm in view.arms or tuple(Arm(treatment=t) for t in sorted({n.treatment for n in view.nca})):
            owner = f"{sid} · {arm.treatment}"
            inputs_rows.append(InputRow(block="protocol", owner=owner, name="ApplicationType", label="Route", value="Oral",
                                        status="sponsor" if (r := next((v for v in view.facts if v.key.startswith("study.route")),
                                                                       None)) else "missing",
                                        sources=r.sources if r else ()))
            if (dose_v and dose_info and dose_info.basis == "salt" and dose_info.dose_as_base_mg is not None
                    and isinstance(dose_v.value, float) and abs(dose_v.value - (dose_info.dose_as_salt_mg or 0)) < 1e-9):
                # the study's dose is the salt's: PK-Sim is given the free base's (R14), both bases on the card
                inputs_rows.append(InputRow(block="protocol", owner=owner, name="InputDose", label="Dose",
                                            value=dose_info.dose_as_base_mg, unit="mg", status="calculated",
                                            sources=dose_v.sources + dose_info.sources, note=dose_info.rule))
            else:
                inputs_rows.append(InputRow(block="protocol", owner=owner, name="InputDose", label="Dose",
                                            value=dose_v.value if dose_v else None,
                                            unit=(dose_v.unit or "mg") if dose_v else "mg",
                                            status=dose_v.status if dose_v else "missing",
                                            sources=dose_v.sources if dose_v else ()))
            if water and isinstance(water.value, float) and weight:
                inputs_rows.append(InputRow(block="protocol", owner=owner, name="Volume of water/body weight",
                                            label="Water with the dose", value=round(water.value / weight[0], 3), unit="ml/kg",
                                            status="calculated", sources=water.sources,
                                            note=f"{water.as_written} ÷ {weight[1]} {weight[0]:g} kg"))
            else:
                # never a silent default: the record says the water is not given, and why (the MAP can show it)
                inputs_rows.append(InputRow(
                    block="protocol", owner=owner, name="Volume of water/body weight", label="Water with the dose",
                    unit="ml/kg", status="missing", sources=water.sources if water else (),
                    note=(f"{water.as_written} stated, but no mean weight to divide it by" if water and
                          isinstance(water.value, float) else f"{water.as_written!r} is not one volume" if water else
                          "the water drunk with the dose is not stated") + f": {WATER_DEFAULT}"))
            profile = next((p for p in view.profiles if p.treatment == arm.treatment and p.analysis_set == set_name), None)
            n = profile.n_subjects if profile else 0
            # each observed profile says its statistic exactly (plan 2026-11-24 §8 feature 5): ours, and the client's
            # as its own table states it
            inputs_rows.append(InputRow(block="observed", owner=owner, name="ObservedData",
                                        label=f"Mean profile, {sets[set_name].label if set_name in sets else set_name}",
                                        value=f"arithmetic mean ± SD (below the LLOQ as 0) and geometric mean (quantifiable "
                                              f"values only), N = {n}",
                                        unit=view.concentration_unit, status="calculated", decision=f"analysis-set:{sid}"))
            for m in view.client_means:
                if (m.group and _code_key(m.group) == _code_key(arm.treatment)) or (not m.group and len(view.arms) <= 1):
                    inputs_rows.append(_client_mean_row(m, owner, view.concentration_unit))
            role = arm.role or ""
            arm_fed = food_of_arm.get(arm.treatment)
            if food_effect and arm_fed == "fed":
                planned, why = "verification", ("a food-effect question: the fed arm is predicted by the model built on "
                                                "the fasted data and checks it, never fitted (MS-01 §3.3 rule 5)")
            elif role == "reference":
                planned, why = "calibration", "the reference product's observed profile sets the model"
            else:
                planned, why = "verification", "the test product's profile checks the model built on the reference"
            plan.append(PlanRow(formulation=arm.product or arm.meaning or arm.treatment,
                                condition=f"{sid}, {arm_fed or 'food not stated'}" + (f", {dose_v.as_written}" if dose_v else ""),
                                observed=f"{sid} {occasion} {arm.treatment} (N = {n})", role=planned,  # type: ignore[arg-type]
                                why=f"{PLAN_PROPOSED}: {why}"))
        codes = {_code_key(a.treatment) for a in view.arms}
        for m in view.client_means:
            # a client's mean profile no arm of the study names: shown on the study, with its statistic
            if not ((m.group and _code_key(m.group) in codes) or (not m.group and len(view.arms) <= 1)):
                inputs_rows.append(_client_mean_row(m, f"{sid} · {m.group}" if m.group else sid, view.concentration_unit))
        meal = chosen.get(f"meal:{sid}")
        times = next((v for v in view.facts if v.key.startswith("study.meal_times")), None)
        if meal:
            # the meal times, and the fed condition's meal where the fed statement times it ("a high-fat breakfast 30
            # minutes before dosing"): the sign of each time is what places it (before the dose: the fed arms only)
            timed = [v for v in (times, fed) if v is not None and meal_times(v.as_written)]
            parsed = sorted({t for v in timed for t in meal_times(v.as_written) or ()}) or None
            inputs_rows.append(InputRow(
                block="event", owner=sid, name=MEAL_HIGH_FAT if meal == "high_fat" else MEAL_STANDARD, label="Meal",
                value="; ".join(f"{t:g}" for t in parsed) if parsed else None, unit="h after the dose (negative: before)",
                status=timed[0].status if parsed else "missing",  # type: ignore[arg-type]
                sources=tuple(c for v in timed for c in v.sources) if parsed else times.sources if times else (),
                decision=f"meal:{sid}",
                note=("as written: " + "; ".join(v.as_written for v in timed)) if parsed else
                (f"no time with its unit in {times.as_written!r}" if times else "no meal time found")))
        for e in view.exposures:
            if e.statistic != "median":
                inputs_rows.append(InputRow(block="target", owner=f"{sid} · {e.treatment}", name=e.metric,
                                            label=f"{e.metric} ({e.statistic.replace('_', ' ')}, {e.analysis_set} set, N = {e.n})",
                                            value=e.value, unit=e.unit, status="verified" if e.difference_percent is not None
                                            and abs(e.difference_percent) <= rules.nca.tolerance_percent else "calculated",
                                            note="" if e.client is None else f"the client's {e.client}"))
    for product in sorted({d.product or d.batch for d in diss}):
        if not any(r.formulation == product for r in plan):
            plan.append(PlanRow(formulation=product, condition="no clinical study", observed="dissolution only",
                                role="prediction", why=f"{PLAN_PROPOSED}: no clinical data: the model predicts its exposure"))

    # --- sections --------------------------------------------------------------------------------------------------------
    written = inputs.writing.get("findings", {})
    basis = inputs.writing.get("basis", {})

    def section(sid: str, title: str, finding: str, ok: bool, empty: bool) -> Section:
        # the writer's line only while code still finds what it found when the line was written: a line written before
        # the room changed said "No dissolution profiles" beside three profiles (a new delivery, 2026-11-24)
        line = written.get(sid) if basis.get(sid) == finding else None
        return Section(id=sid, title=title, finding=line or finding, computed=finding,
                       status="empty" if empty else ("ok" if ok else "attention"))

    n_ocr = sum(len(f.ocr_pages) for f in inputs.files)
    open_requests = [r for r in requests if r.status == "open"]
    # the exposure numbers recomputed beside the client's: how many agree within the NCA tolerance
    compared = [e.difference_percent for s in studies for e in s.exposures
                if e.difference_percent is not None and e.metric != "tmax"]
    agree = sum(1 for d in compared if abs(d) <= rules.nca.tolerance_percent)
    # the arms of each study in its chosen analysis set (a profile is kept per set and arm)
    arms = sum(1 for s in studies for p in s.profiles if p.analysis_set == chosen.get(f"analysis-set:{s.study_id}", "modeling"))
    observed_finding = (f"{arms} mean profiles; {agree} of {len(compared)} of the client's exposure numbers reproduced within "
                        f"{rules.nca.tolerance_percent:g} %" if compared else f"{arms} mean profiles; no client exposure to compare")
    # a subject's own value off can hide in an arm's geometric mean: said beside it (a new delivery, 2026-11-24)
    differing = sum(1 for s in studies for p in s.problems if p.code == "NCA_DIFFERS")
    if differing:
        observed_finding += f"; {differing} subject {'value differs' if differing == 1 else 'values differ'} from the client's"
    sections = [
        section("files", "Files", f"{len(inputs.files)} files read" + (f", {n_ocr} scanned pages read by our OCR" if n_ocr else ""),
                all(f.state in ("read", "partly_read") for f in inputs.files), not inputs.files),
        section("requirements", "Requirements for this question", *checklist.finding(needs)),
        section("substance", "Drug substance", f"{len(substance)} {'property' if len(substance) == 1 else 'properties'} found",
                not any(v.status == "conflict" for v in substance), not substance),
        section("adme", "ADME and disposition", f"{len(adme)} {'fact' if len(adme) == 1 else 'facts'} found", True, not adme),
        section("formulation", "Formulation", f"{len(composition)} components, {sum(1 for c in composition if c.changed)} changed"
                + (f"; {len(checks['formulation'])} functional class{'es differ' if len(checks['formulation']) > 1 else ' differs'}"
                   if checks.get("formulation") else ""), not checks.get("formulation"), not composition),
        section("solubility", "Solubility", f"{len(solubility)} media" + (
            f"; the dose number is above 1 in {limited} of them" if (limited := max(
                (sum(1 for x in a.dose_numbers if x.dose_number > 1) for a in absorption), default=0)) else ""),
                True, not solubility),
        section("dissolution", "Dissolution", f"{len(diss)} profiles; {sum(1 for d in diss if d.very_rapid)} release ≥ 85 % "
                "within 15 min", not any(d.problems for d in diss) and not checks.get("dissolution"), not diss),
        section("clinical", "Clinical studies", "; ".join(
            f"{s.study_id}: {len(next((x.subjects for x in s.sets if x.name == 'modeling'), ()))} subjects in the modeling set"
            for s in studies), not any(p.severity == "error" for s in studies for p in s.problems), not studies),
        section("observed", "Observed PK", observed_finding, all(abs(d) <= rules.nca.tolerance_percent for d in compared),
                not any(s.profiles for s in studies)),
        section("decisions", "Decisions", f"{sum(1 for d in decisions if not d.chosen)} waiting", all(d.chosen for d in decisions),
                not decisions),
        section("requests", "Data requests", f"{len(open_requests)} open", not open_requests, not requests),
        section("plan", "Simulation plan", f"{len(plan)} simulations: " + ", ".join(
            f"{n} {role}" for role in ("calibration", "verification", "prediction")
            if (n := sum(1 for r in plan if r.role == role))), True, not plan),
        section("inputs", "PK-Sim inputs", f"{sum(1 for r in inputs_rows if r.status != 'missing')} of {len(inputs_rows)} filled",
                not any(r.status == "missing" for r in inputs_rows), not inputs_rows),
    ]
    view = DataRoomView(rules=rules.label(), files=tuple(inputs.files), question=question,
                        question_confirmed=inputs.question_confirmed, sections=tuple(sections), substance=tuple(substance),
                        adme=tuple(adme), products=tuple(products), composition=tuple(composition), solubility=tuple(solubility),
                        absorption=tuple(absorption), dissolution=tuple(diss), f2=tuple(f2s), studies=tuple(studies),
                        other_analytes=tuple(other_analytes), dose_card=dose_info, decisions=tuple(decisions),
                        requests=tuple(requests), plan=tuple(plan), inputs=tuple(inputs_rows),
                        problems=tuple(problems), checks=checks, requirements=needs)
    # the page in its groups (plan 2026-11-26 §9, slice 5a): code places every part, the page draws it
    return view.model_copy(update={"layout": build_layout(
        view, required=required_from_drafts(needs.items if needs else ()))})


# a value the files state was fitted to clinical PK, not measured
_FITTED = re.compile(r"(?i)\bfitted\b|\bfit\s+(?:to|against|on)\b|\boptimi[sz]ed\b|parameter\s+identification|"
                     r"\bestimated\s+from\s+(?:the\s+)?(?:clinical|in\s+vivo|plasma|pk)\b|back[-\s]?calculated")


def _permeability(substance: Sequence[Value], rules: Rules, products: Sequence[str]
                  ) -> tuple[list[Value], list[Value], list[Value]]:
    """The substance values with each permeability sorted (plan 2026-11-24 §8 feature 6): a value the files give for one
    of the lab's reference compounds (`permeability.reference_compounds`: its fact's subject names it, or, with no
    subject, its quote) is that calibration set's evidence, never the drug's permeability; a value the files state was
    fitted to clinical PK says so. A reference compound that is the drug itself (named in a product) is the drug's.
    Returns the substance values, the drug's own permeabilities and the reference compounds'."""
    from modeler_project.dataroom.rules import first_named

    out: list[Value] = []
    own: list[Value] = []
    refs: list[Value] = []
    for v in substance:
        if not v.key.startswith("substance.permeability"):
            out.append(v)
            continue
        subject = v.key.split("[", 1)[1].rstrip("]") if "[" in v.key else ""
        quote = " ".join([v.as_written] + [c.text for c in v.sources])
        ref = rules.reference_compound(subject) if subject else rules.reference_compound(quote)
        if ref and not first_named(" ".join(products), [(ref, True)]):
            v = v.model_copy(update={
                "key": f"substance.permeability.reference[{ref}]",
                "label": f"Permeability of {ref}, a reference compound of the lab's assay",
                "note": "the lab's calibration set: evidence for calibrating the assay, not the drug's permeability"})
            refs.append(v)
        else:
            if _FITTED.search(quote):
                fitted = "the files state it was fitted to clinical PK: a fitted value, not a measurement"
                v = v.model_copy(update={"note": "; ".join(x for x in (v.note, fitted) if x)})
            own.append(v)
        out.append(v)
    return out, own, refs


def _doses(facts: Sequence[CheckedFact], question: QuestionCard | None, fallback: CheckedFact | None
           ) -> list[tuple[str, float, str, tuple[Chip, ...]]]:
    """Each card product's dose for the absorption checks: its own strength fact, else the room's one dose (the first
    strength or the study's dose); (product, mg, as written, sources). With no card: the room's dose for the drug."""
    names = [p.name for p in (question.products if question else ())]
    strengths = [f for f in facts if f.ok and f.fact.field == "product.strength" and f.number]
    out = []
    for name in names:
        f = next((f for f in strengths if named_in(f.fact.product or f.fact.subject, [name]) == name), None) or fallback
        if f is not None and f.number:
            out.append((name, f.number, f"{f.fact.value} {f.fact.unit}".strip(), (f.chip,) if f.chip else ()))
    if not names and fallback is not None and fallback.number:
        out.append(("", fallback.number, f"{fallback.fact.value} {fallback.fact.unit}".strip(),
                    (fallback.chip,) if fallback.chip else ()))
    return out


def _by_dose(doses: Sequence[tuple[str, float, str, tuple[Chip, ...]]]
             ) -> dict[tuple[float, str, tuple[Chip, ...]], list[str]]:
    """The products of each dose, so one statement names every product that dose stands for."""
    out: dict[tuple[float, str, tuple[Chip, ...]], list[str]] = {}
    for product, mg, written, chips in doses:
        key = next((k for k in out if k[0] == mg), (mg, written, chips))
        out.setdefault(key, []).append(product)
    return {k: [p for p in v if p] for k, v in out.items()}


def _client_mean_row(m: ClientMean, owner: str, unit: str) -> InputRow:
    """The client's own mean profile as an observed-data row: its statistic and spread exactly as its table states them;
    Missing while the table does not say which statistic it is."""
    return InputRow(block="observed", owner=owner, name="ObservedData",
                    label="The client's mean profile" + (f" ({m.group})" if m.group else ""), value=statistic_words(m),
                    unit=m.unit or unit, status="sponsor" if m.statistic else "missing", sources=m.sources,
                    note=m.note if m.statistic else "the table does not state its statistic: ask before comparing it")


def _field_label(field: str) -> str:
    """A fact's field as a person reads it: the vocabulary's words ("molecular weight"), else its last name part."""
    from modeler_intake.room_specs import FIELDS

    return FIELDS.get(field) or field.rsplit(".", 1)[-1].replace("_", " ")


def _pka_rows(facts: Sequence[CheckedFact], substance: Sequence[Value]) -> list[InputRow]:
    """One row per stated pKa: acid or base by the words beside it (phys.pka.acid.N / phys.pka.base.N, as plan §7.1);
    a pKa whose type is not stated, or that is not one number, is Missing with the reason, never guessed."""
    rows: list[InputRow] = []
    seen: dict[str, int] = defaultdict(int)
    conflict = any(v.key.startswith("substance.pka") and v.status == "conflict" for v in substance)
    for f in facts:
        kind = pka_type(f"{f.fact.value} {f.fact.quote}")      # the file's words, never the agent's note
        value = number_of(f.fact.value, f.fact.unit)
        chip = (f.chip,) if f.chip else ()
        if value is None or kind is None:
            rows.append(InputRow(block="compound", name="phys.pka", label="pKa", status="missing", sources=chip,
                                 note=("not one number as written" if value is None else "its type (acid or base) is not "
                                       "stated") + f": {f.fact.value!r}"))
            continue
        key = f"phys.pka.{kind}.{seen[kind]}"
        seen[kind] += 1
        rows.append(InputRow(block="compound", name=key, label=f"pKa ({'acidic' if kind == 'acid' else 'basic'})", value=value,
                             status="conflict" if conflict else "sponsor", sources=chip))
    return rows


def label_of(key: str) -> str:
    return next((label for k, label, _f, _u in COMPOUND if k == key), key)


def chips_of(view: DataRoomView) -> list[Chip]:
    """Every source chip the view shows (for checking that each opens its place)."""
    out: list[Chip] = []
    for v in (*view.substance, *view.adme, *view.products):
        out += v.sources
    for s in view.studies:
        for v in s.facts:
            out += v.sources
    for d in view.dissolution:
        out += d.sources
    return out
