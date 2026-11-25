"""What the question needs (plan 2026-11-24 §6, phase 2): the requirement drafts per context of use, read against the room.

Code reads the question card and the room; the AI is asked nothing new:

1. **Which applications.** The card's question, approach, context of use and regulator are matched, by whole words,
   against a small phrase table (`PHRASES`): "food effect" or "fed" reads food effect, "biowaiver" or "PBBM" reads
   PBBM bridging and virtual BE, and so on. One decision (`applications`) offers what was read together (suggested),
   each application alone, and none (the core items only); the checklist follows the choice, and until a person makes
   it, the suggestion, labelled "as read from the question card".
2. **Properties and triggers.** The properties core.yaml says code can determine are read from the room's facts and
   tables (`properties`): a weak base from a pKa of type base, the solubility fall from the solubility rows, a salt
   from the salt-form fact, and so on. Anything else is not known. A CONDITIONAL item applies when its trigger holds,
   is not applicable when it fails, and otherwise "applies if … (not known from the delivery)". A cut-off the SME sets
   is never invented: such a condition is not known, and the trigger is decided only where the rest decides it.
3. **The ledger.** Each item of the chosen applications (core items merged, overrides applied; the stricter status
   wins across applications) says where the room covers it: found (which facts, tables, files), missing (which files
   were searched), not needed (why), kept as context, or for a person to check where the room has no place for it.
4. **Data requests.** `asks` names the missing items that become the room's data requests: what, why, the accepted
   alternatives, "(draft requirement, UNVERIFIED)". Nothing NOT_NEEDED or inapplicable is ever asked for.

Every item and request carries the drafts' label: draft, UNVERIFIED, awaiting the owner's and the SME's review. No data
plan, gate or live template reads any of it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from modeler_intake.room_specs import FIELDS, ChecklistItem, QuestionCard
from modeler_project.dataroom.drafts import LABEL, Condition, DraftItem, Drafts, Trigger, load_drafts
from modeler_project.dataroom.extract import number_of
from modeler_project.dataroom.model import (
    CheckedFact,
    Chip,
    DataRequest,
    FileView,
    Option,
    PropertyRead,
    ReadPhrase,
    ReadTable,
    RequirementItem,
    Requirements,
    RoomDecision,
    SolubilityRow,
    Value,
)

DECISION = "applications"
NONE = "none"
#: the words every data request from a draft carries
DRAFT_WORDS = "(draft requirement, UNVERIFIED)"

# Which checklist topics a fact field (by prefix) or a table kind covers (the room's own map, used for its requests too)
TOPIC_FIELDS: dict[str, tuple[str, ...]] = {
    "clinical_design": ("study.design", "study.id", "study.regimen"), "dosing_and_meals": ("study.dose", "study.fed",
    "study.fasting", "study.meal", "study.water"), "clinical_demographics": ("study.age", "study.weight", "study.sex"),
    "clinical_disposition": ("study.completed", "study.excluded", "study.n_"), "bioanalysis": ("study.lloq",
    "study.analyte", "study.matrix"), "be_statistics": ("study.be_result",), "drug_substance": ("substance.",),
    "adme": ("adme.",), "composition": ("product.composition",), "solubility": ("substance.solubility",),
    "particle_size": ("substance.particle_size",), "label": ("adme.", "substance.")}
TOPIC_TABLES: dict[str, tuple[str, ...]] = {
    "clinical_concentrations": ("concentrations",), "clinical_pk": ("pk_parameters",),
    "clinical_demographics": ("demographics",), "clinical_disposition": ("disposition",), "dissolution": ("dissolution",),
    "composition": ("composition",), "solubility": ("solubility",), "particle_size": ("particle_size",),
    "be_statistics": ("be_statistics",), "drug_substance": ("physchem",)}
# a checklist topic that names paperwork, not data
PAPERWORK = frozenset({"question", "regulatory", "quality_paperwork", "other"})
# a fact field whose values the room also reads from a table of their own (a solubility table holds solubilities)
FIELD_TABLES: dict[str, str] = {"substance.solubility": "solubility", "substance.particle_size": "particle_size"}


# --- 1. which applications -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Application:
    id: str                          # the draft file, with its sub-context after a dot
    file: str
    subcontext: str
    label: str


APPLICATIONS: tuple[Application, ...] = (
    Application("pbbm_bridging_vbe", "pbbm_bridging_vbe", "", "PBBM, bridging and virtual BE"),
    Application("food_effect", "food_effect", "", "Food effect"),
    Application("acid_reducing_agents", "acid_reducing_agents", "", "Acid-reducing agents"),
    Application("ddi_victim", "ddi_victim", "", "DDI, the drug as victim"),
    Application("ddi_perpetrator", "ddi_perpetrator", "", "DDI, the drug as perpetrator"),
    Application("transporter_ddi", "transporter_ddi", "", "Transporter DDI"),
    Application("pediatric", "pediatric", "", "Paediatrics"),
    Application("organ_impairment.renal_impairment", "organ_impairment", "renal_impairment", "Renal impairment"),
    Application("organ_impairment.hepatic_impairment", "organ_impairment", "hepatic_impairment", "Hepatic impairment"),
    Application("fih_dose_prediction", "fih_dose_prediction", "", "First-in-human dose"),
    Application("special_populations.pregnancy", "special_populations", "pregnancy", "Pregnancy"),
    Application("special_populations.geriatrics", "special_populations", "geriatrics", "The elderly"),
    Application("special_populations.ethnicity", "special_populations", "ethnicity", "An ethnic population"),
)
_BY_ID = {a.id: a for a in APPLICATIONS}

# The phrase table: the words (whole words, any case; a regular expression each) and the applications they read.
PHRASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    ((r"food[- ]effects?", r"fed", r"fed[- ]state", r"with food"), ("food_effect",)),
    ((r"DDIs?", r"drug[-–‑ ]drug interactions?", r"interactions?", r"inhibitors?", r"inducers?", r"CYP\w*"),
     ("ddi_victim", "ddi_perpetrator")),
    ((r"transporters?", r"OATP\w*", r"P-?gp", r"P-glycoprotein", r"BCRP"), ("transporter_ddi",)),
    ((r"pa?ediatrics?", r"children", r"infants?", r"neonat\w*"), ("pediatric",)),
    ((r"renal impairment", r"kidney impairment", r"renal insufficiency"), ("organ_impairment.renal_impairment",)),
    ((r"hepatic impairment", r"liver impairment", r"hepatic insufficiency"), ("organ_impairment.hepatic_impairment",)),
    ((r"organ impairment",), ("organ_impairment.renal_impairment", "organ_impairment.hepatic_impairment")),
    ((r"bioequivalen\w*", r"VBE", r"virtual BE", r"formulation changes?", r"bridg\w*", r"site changes?", r"scale[- ]up",
      r"safe space", r"dissolution specifications?", r"PBBM", r"biowaivers?"), ("pbbm_bridging_vbe",)),
    ((r"acid[- ]reduc\w*", r"PPIs?", r"proton[- ]pumps?", r"H2", r"antacids?", r"pH[- ]dependent"), ("acid_reducing_agents",)),
    ((r"first[- ]in[- ]human", r"FIH", r"starting doses?"), ("fih_dose_prediction",)),
    ((r"pregnan\w*",), ("special_populations.pregnancy",)),
    ((r"elderly", r"geriatrics?"), ("special_populations.geriatrics",)),
    ((r"ethnic\w*",), ("special_populations.ethnicity",)),
)
# which side of a DDI the words point to; when they name neither side, or both, the question reads as both
DDI_SIDES: tuple[tuple[tuple[str, ...], str], ...] = (
    ((r"victims?", r"object drugs?"), "ddi_victim"),
    ((r"perpetrators?", r"precipitants?", r"inhibits", r"induces"), "ddi_perpetrator"),
)
_CARD_FIELDS = ("question", "approach", "context_of_use", "regulator")


def _whole(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", re.IGNORECASE)


_PHRASES = tuple((tuple(_whole(p) for p in words), apps) for words, apps in PHRASES)
_SIDES = tuple((tuple(_whole(p) for p in words), app) for words, app in DDI_SIDES)


def _hits(patterns: Iterable[re.Pattern[str]], card: QuestionCard) -> list[str]:
    out: list[str] = []
    for name in _CARD_FIELDS:
        text = getattr(card, name) or ""
        for p in patterns:
            for m in p.finditer(text):
                out.append(f"'{m.group(0)}' ({name.replace('_', ' ')})")
    return list(dict.fromkeys(out))


def read_applications(card: QuestionCard | None) -> dict[str, tuple[str, ...]]:
    """The applications the card's words name, each with the words that matched, in `APPLICATIONS` order."""
    if card is None:
        return {}
    found: dict[str, list[str]] = {}
    for patterns, apps in _PHRASES:
        words = _hits(patterns, card)
        if not words:
            continue
        if apps == ("ddi_victim", "ddi_perpetrator"):
            sides = {app: _hits(side, card) for side, app in _SIDES}
            named = [app for app, said in sides.items() if said]
            if len(named) == 1:
                apps = (named[0],)
                words = words + sides[named[0]]
        for app in apps:
            found.setdefault(app, []).extend(words)
    return {a.id: tuple(dict.fromkeys(found[a.id])) for a in APPLICATIONS if a.id in found}


def applications_decision(card: QuestionCard | None, made: Mapping[str, Mapping[str, str]]) -> RoomDecision | None:
    """The decision "which applications": what the card reads as together (suggested), each alone, and none."""
    if card is None:
        return None
    read = read_applications(card)
    found = [_BY_ID[a] for a in read]
    options: list[Option] = []
    if len(found) > 1:
        options.append(Option(id="+".join(a.id for a in found), label=" + ".join(a.label for a in found),
                              detail="read from " + "; ".join(", ".join(read[a.id]) for a in found)))
    options += [Option(id=a.id, label=a.label, detail="read from " + ", ".join(read[a.id])) for a in found]
    options.append(Option(id=NONE, label="None of these (core items only)",
                          detail="the items every context of use starts from"))
    why = ("as read from the question card: " + "; ".join(f"{', '.join(read[a.id])} → {a.label}" for a in found)
           if found else "the question card names none of the applications the drafts cover: the core items only")
    decision = RoomDecision(
        id=DECISION, title="Applications of the question",
        question=("Which applications is the model for? The checklist of what the delivery must hold follows the choice "
                  f"({LABEL})."), options=tuple(options), suggested=options[0].id, why=why)
    chosen = made.get(DECISION)
    if chosen and chosen.get("chosen") in {o.id for o in options}:
        # a choice stands while the card still offers it (a changed card can offer other options)
        decision = decision.model_copy(update={"chosen": chosen["chosen"], "reason": chosen.get("reason", ""),
                                               "by": chosen.get("by", ""), "at": chosen.get("at", "")})
    return decision


def chosen_applications(decision: RoomDecision | None) -> tuple[Application, ...]:
    """The applications in force: the person's choice, else the suggestion."""
    if decision is None:
        return ()
    pick = decision.chosen or decision.suggested
    return tuple(_BY_ID[x] for x in pick.split("+") if x in _BY_ID)


# --- 2. properties and triggers --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """What the room read, as the checklist needs it (assembled by `modeler_project.dataroom.assemble`)."""

    facts: Sequence[CheckedFact]
    tables: Sequence[ReadTable]
    files: Sequence[FileView]
    solubility: Sequence[SolubilityRow] = ()
    pkas: Sequence[tuple[str | None, float | None, Chip | None]] = ()   # each pKa fact: acid / base / None, value, source
    cell_permeability: Sequence[Value] = ()     # the drug's permeabilities measured in a cell or membrane assay
    entered: Mapping[str, Value] | None = None  # values a person entered, by the room field they stand for
    arm_food: Sequence[tuple[str, Chip | None]] = ()   # each study arm's food state by its own words (fed / fasted)

    def ok(self, field: str) -> list[CheckedFact]:
        return [f for f in self.facts if f.ok and f.fact.field == field]


@dataclass(frozen=True)
class Prop:
    known: bool = False
    value: Any = None                # bool, float, str or frozenset of names
    basis: str = ""
    chips: tuple[Chip, ...] = ()


def _chips(facts: Iterable[CheckedFact]) -> tuple[Chip, ...]:
    return tuple(dict.fromkeys(f.chip for f in facts if f.chip))


def _text(f: CheckedFact, quote: bool = True) -> str:
    return " ".join(x for x in (f.fact.subject, f.fact.value, f.fact.quote if quote else "") if x)


_NEGATED = re.compile(r"\bnot\b|\bno\b|n't\b|\bnone\b|\bnegligible\b|\bnon-?substrate", re.IGNORECASE)
_ENZYME = re.compile(r"\b(CYP\s?\d{1,2}[A-Z]{0,2}\d{0,2}|UGT\s?\d[A-Z]\d{0,2}|FMO\d?|SULT\s?\d[A-Z]?\d{0,2}|CES\d|"
                     r"aldehyde oxidase|AOX1?|MAO-?[AB]|NAT[12])\b", re.IGNORECASE)
_NOT_METABOLISED = re.compile(r"\bnot\s+(?:\w+\s+){0,2}metaboli[sz]ed\b|\bno\s+(?:\w+\s+){0,2}metabolism\b|"
                              r"\b(?:excreted|eliminated)\s+(?:entirely|completely|wholly)\s+unchanged\b", re.IGNORECASE)
_TRANSPORTER = re.compile(r"\b(P-?gp|P-glycoprotein|MDR1|ABCB1|BCRP|ABCG2|OATP\s?\d[A-Z]\d|OATP\w*|OAT\s?\d|OCT\s?\d|"
                          r"MATE\s?-?\d(?:-?K)?|BSEP|MRP\s?\d|NTCP|ENT\d|PEPT\d)\b", re.IGNORECASE)
_SALT = re.compile(r"\bsalt\b|hydrochloride|\bHCl\b|mesylate|mesilate|besylate|besilate|maleate|fumarate|tartrate|citrate|"
                   r"succinate|sulfate|sulphate|phosphate|acetate|tosylate|bromide|chloride|\bsodium\b|potassium|"
                   r"calcium|magnesium|meglumine|tromethamine", re.IGNORECASE)
_FREE = re.compile(r"\bfree\s+(?:base|acid|form)\b|\bnot\s+a\s+salt\b|\bno\s+salt\b", re.IGNORECASE)
_NEUTRAL = re.compile(r"\bneutral\b|non-?ioni[sz]able|\bno\s+ioni[sz]able\b", re.IGNORECASE)
_BCS = re.compile(r"\b(?:BCS\s*)?(?:class\s*)?(IV|III|II|I|[1-4])\b", re.IGNORECASE)
_ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV"}
_FED_CARD = re.compile(r"\bfed\b|food[- ]effects?|\bwith food\b|\bhigh[- ]fat\b", re.IGNORECASE)
# a "fed" fact that is no fed dosing: none, fasted, or a meal served after the dose ("breakfast 2 h after dosing")
_NOT_FED = re.compile(r"^\s*(?:no|none|not|n/?a|-|—)\b|\bfasted\b|\bfasting\b|\bafter\s+(?:the\s+)?dos(?:e|ing)\b|"
                      r"\bpost[- ]?dose\b|\bafter\s+(?:drug\s+)?administration\b", re.IGNORECASE)


def pka_values(facts: Iterable[CheckedFact], typed: Any) -> list[tuple[str | None, float | None, Chip | None]]:
    """Each pKa a fact gives, with its type by the file's words (`typed`: text -> "acid", "base" or None): one fact may
    give several ("pKa1 (basic, pyridine N) = 4.1; pKa2 (acidic, benzimidazole N-H) = 9.3"), each typed by its own
    piece; a single pKa by its value and quote, as the room's PK-Sim inputs read it."""
    out: list[tuple[str | None, float | None, Chip | None]] = []
    for f in facts:
        if not f.ok or f.fact.field != "substance.pka":
            continue
        pieces = [p for p in re.split(r";|\n", f.fact.value) if re.search(r"\d", p)]
        if len(pieces) > 1:
            for piece in pieces:
                numbers = re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?!\w)", piece)   # not the 1 of "pKa1"
                out.append((typed(piece), float(numbers[-1]) if numbers else None, f.chip))
        else:
            out.append((typed(f"{f.fact.value} {f.fact.quote}"), number_of(f.fact.value, f.fact.unit), f.chip))
    return out


def _clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[.;,\n]|\band\s+not\b|\bbut\b", text) if c.strip()]


def _names(text: str, pattern: re.Pattern[str], norm: Any) -> tuple[set[str], set[str]]:
    """The names a text gives, and those it gives in a negated clause ("not a P-gp substrate")."""
    said, negated = set(), set()
    for clause in _clauses(text):
        got = {norm(m.group(1)) for m in pattern.finditer(clause)}
        (negated if _NEGATED.search(clause) else said).update(got)
    return said, negated - said


def _enzyme(name: str) -> str:
    return re.sub(r"\s+", "", name).upper().replace("ALDEHYDEOXIDASE", "AOX")


def _transporter(name: str) -> str:
    n = re.sub(r"\s+", "", name).upper()
    return {"PGP": "P-GP", "P-GLYCOPROTEIN": "P-GP", "MDR1": "P-GP", "ABCB1": "P-GP", "ABCG2": "BCRP"}.get(n, n)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


# the properties `properties` reads from the room; every other one of core.yaml's vocabulary stays not known (a person
# answers it, or it needs a cut-off the SME sets: an adult food effect)
_CODE_READS = frozenset({"weak_base", "highest_basic_pka", "solubility_ratio_gastric_to_intestinal", "salt_form", "bcs_class",
                         "metabolised", "metabolising_enzymes", "fraction_excreted_unchanged", "transporter_families",
                         "in_vitro_permeability_supplied", "individual_data_available", "fed_dosing_in_scope",
                         "reference_product_in_question"})


def properties(card: QuestionCard | None, ev: Evidence) -> dict[str, Prop]:
    """The properties code determines from the room (core.yaml `how: code`, and a BCS class the delivery states). A
    property code cannot determine is absent: not known."""
    out: dict[str, Prop] = {}
    # pKa and its type: a weak base, its highest basic pKa
    typed = [(k, n, c) for k, n, c in ev.pkas]
    bases = [(n, c) for k, n, c in typed if k == "base"]
    pka_chips = tuple(c for _k, _n, c in typed if c)
    if bases:
        out["weak_base"] = Prop(True, True, "a pKa of type base: " + ", ".join(f"{n:g}" for n, _c in bases if n is not None),
                                tuple(c for _n, c in bases if c))
        numbers = [n for n, _c in bases if n is not None]
        if numbers:
            out["highest_basic_pka"] = Prop(True, max(numbers), f"the highest basic pKa given: {max(numbers):g}",
                                            tuple(c for _n, c in bases if c))
    elif typed and all(k == "acid" for k, _n, _c in typed):
        out["weak_base"] = Prop(True, False, "every pKa given is acidic", pka_chips)
    elif neutral := [f for f in ev.ok("substance.pka") if _NEUTRAL.search(_text(f))]:
        out["weak_base"] = Prop(True, False, "the delivery states the drug is neutral", _chips(neutral))
    # the solubility fall from gastric (pH 1-2) to intestinal (about pH 6.5) pH (PBBM review §5 idea 7)
    rows = [r for r in ev.solubility if r.ph is not None and r.solubility_mg_ml is not None]
    gastric = max((r for r in rows if 1.0 <= r.ph <= 2.0), key=lambda r: r.solubility_mg_ml or 0.0, default=None)  # type: ignore[operator]
    intestinal = min((r for r in rows if abs(r.ph - 6.5) <= 0.5), key=lambda r: abs(r.ph - 6.5), default=None)  # type: ignore[operator]
    if gastric and intestinal and intestinal.solubility_mg_ml:
        ratio = gastric.solubility_mg_ml / intestinal.solubility_mg_ml  # type: ignore[operator]
        out["solubility_ratio_gastric_to_intestinal"] = Prop(
            True, ratio, f"{gastric.as_written or gastric.solubility_mg_ml} at pH {gastric.ph:g} ÷ "
            f"{intestinal.as_written or intestinal.solubility_mg_ml} at pH {intestinal.ph:g} = {ratio:.3g}",
            gastric.sources[:1] + intestinal.sources[:1])
    elif intestinal and intestinal.solubility_mg_ml and (bound := next(
            (r for r in ev.solubility if r.ph is not None and 1.0 <= r.ph <= 2.0 and r.solubility_mg_ml is None
             and r.as_written.strip().startswith(">")), None)):
        # a gastric solubility written as a bound ("> 20 mg/mL"): the ratio is not one number, so it stays not known
        out["solubility_ratio_gastric_to_intestinal"] = Prop(
            False, None, f"the solubility at pH {bound.ph:g} is a bound ({bound.as_written.split(' at ')[0]}), so the fall "
            f"to pH {intestinal.ph:g} ({intestinal.as_written.split(' at ')[0]}) is not one number",
            bound.sources[:1] + intestinal.sources[:1])
    # a salt
    salts = ev.ok("substance.salt")
    for f in salts:
        value = f.fact.value
        if _SALT.search(value) and not _FREE.search(value):
            out["salt_form"] = Prop(True, True, f"the salt form is given: {value}", _chips([f]))
            break
    else:
        free = [f for f in salts if _FREE.search(_text(f))]
        if free:
            out["salt_form"] = Prop(True, False, f"the delivery states the free form: {free[0].fact.value}", _chips(free))
        elif said := [f for f in salts if _SALT.search(_text(f))]:
            out["salt_form"] = Prop(True, True, f"the salt form is given: {said[0].fact.value}", _chips(said))
    # a BCS class the delivery states (the room never computes one)
    classes = {}
    for f in ev.ok("substance.bcs"):
        if m := _BCS.search(f.fact.value):
            classes[_ROMAN.get(m.group(1), m.group(1).upper())] = f
    if len(classes) == 1:
        ((bcs, f),) = classes.items()
        out["bcs_class"] = Prop(True, bcs, f"stated: {f.fact.value}", _chips([f]))
    # metabolism: the enzymes named, or a statement that the drug is not metabolised
    metabolism = ev.ok("adme.metabolism")
    enzymes: set[str] = set()
    named = []
    for f in metabolism:
        said, _not = _names(_text(f, quote=False), _ENZYME, _enzyme)
        if not said:
            said, _not = _names(f.fact.quote, _ENZYME, _enzyme)
        if said:
            enzymes |= said
            named.append(f)
    if enzymes:
        out["metabolised"] = Prop(True, True, "the metabolism facts name " + ", ".join(sorted(enzymes)), _chips(named))
        out["metabolising_enzymes"] = Prop(True, frozenset(enzymes), ", ".join(sorted(enzymes)), _chips(named))
    elif stated := [f for f in [*metabolism, *ev.ok("adme.excretion")] if _NOT_METABOLISED.search(_text(f))]:
        out["metabolised"] = Prop(True, False, f"stated: {stated[0].fact.value}", _chips(stated))
        out["metabolising_enzymes"] = Prop(True, frozenset(), "none: the drug is stated not to be metabolised", _chips(stated))
    # the fraction of the dose excreted unchanged in urine, as reported
    for f in ev.ok("adme.excretion"):
        for clause in re.split(r"[.;\n]", _text(f)):
            if not re.search(r"urin|renal", clause, re.IGNORECASE) or not re.search(r"unchanged", clause, re.IGNORECASE):
                continue
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", clause)
            if m:
                fe = float(m.group(1)) / 100
                out["fraction_excreted_unchanged"] = Prop(True, fe, f"{m.group(0)} of the dose unchanged in urine", _chips([f]))
                break
        if "fraction_excreted_unchanged" in out:
            break
    # transporters named (a negated clause names none)
    transporters: set[str] = set()
    tnamed = []
    for f in ev.ok("adme.transporters"):
        said, _not = _names(_text(f, quote=False), _TRANSPORTER, _transporter)
        if not said:
            said, _not = _names(f.fact.quote, _TRANSPORTER, _transporter)
        if said:
            transporters |= said
            tnamed.append(f)
    if transporters:
        out["transporter_families"] = Prop(True, frozenset(transporters), ", ".join(sorted(transporters)), _chips(tnamed))
    # an in vitro permeability supplied (Caco-2, MDCK, PAMPA): the room read the whole delivery, so none is "no"
    if ev.cell_permeability:
        v = ev.cell_permeability[0]
        out["in_vitro_permeability_supplied"] = Prop(True, True, f"{v.as_written} {v.unit}".strip(),
                                                     tuple(c for v in ev.cell_permeability for c in v.sources[:1]))
    else:
        out["in_vitro_permeability_supplied"] = Prop(True, False, "no permeability from a cell or membrane assay was read")
    # subject-level concentrations
    individual = [t for t in ev.tables if t.description.kind == "concentrations"
                  and any(c.role == "subject" for c in t.description.columns)]
    out["individual_data_available"] = Prop(
        True, bool(individual), f"{len(individual)} concentrations table(s) with a subject column" if individual else
        "no concentrations table with a subject column", tuple(_table_chip(t) for t in individual if _table_chip(t)))
    # fed dosing in scope: the question names it, or a study or an arm is fed; not when the studies are fasted only
    card_words = [m.group(0) for name in _CARD_FIELDS for m in _FED_CARD.finditer(getattr(card, name, "") or "")] if card else []
    fed_facts = [f for f in ev.ok("study.fed") if not _NOT_FED.search(f.fact.value)]
    fed_arms = [c for food, c in ev.arm_food if food == "fed"]
    fasted = [*ev.ok("study.fasting")]
    fasted_arms = [c for food, c in ev.arm_food if food == "fasted"]
    if card_words or fed_facts or fed_arms:
        basis = "; ".join(x for x in (f"the question card says {', '.join(dict.fromkeys(card_words))}" if card_words else "",
                                      f"{len(fed_facts)} fed study fact(s)" if fed_facts else "",
                                      f"{len(fed_arms)} arm(s) dosed fed" if fed_arms else "") if x)
        out["fed_dosing_in_scope"] = Prop(True, True, basis, _chips(fed_facts) + tuple(c for c in fed_arms if c))
    elif fasted or fasted_arms:
        out["fed_dosing_in_scope"] = Prop(True, False, "the studies read are fasted and the question names no fed dosing",
                                          _chips(fasted) + tuple(c for c in fasted_arms if c))
    # a reference product in the question
    if card is not None:
        refs = [p.name for p in card.products if p.role == "reference"]
        out["reference_product_in_question"] = Prop(True, bool(refs), "the question card's reference product: " + refs[0]
                                                    if refs else "the question card names no reference product")
    return out


def _table_chip(t: ReadTable) -> Chip | None:
    for row in t.rows:
        for cell in row.cells:
            return cell.chip
    return None


State = str     # "yes", "no", "unknown"


def _property_label(name: str) -> str:
    return name.replace("_", " ").replace("pka", "pKa").replace("bcs", "BCS")


def _condition(c: Condition, props: Mapping[str, Prop]) -> tuple[State, str]:
    p = props.get(c.property)
    label = _property_label(c.property)
    if c.test == "sme":
        seen = f"; {_shown(p.value)} as read" if p and p.known else ""
        return "unknown", f"{label} {c.direction} a cut-off the SME sets: not known (no cut-off is set yet{seen})"
    if p is None or not p.known:
        return "unknown", f"{label}: not known from the delivery"
    if c.test == "equals":
        state = p.value == c.value
        return _yes_no(state), f"{label}: {_shown(p.value)}"
    if c.test == "in":
        return _yes_no(p.value in (c.value or ())), f"{label}: {_shown(p.value)}"
    if c.test == "any_of":
        members = {re.sub(r"[-\s]", "", str(m)).upper() for m in p.value}
        wanted = [re.sub(r"[-\s]", "", str(w)).upper() for w in (c.value or ())]
        hit = any(m.startswith(w) for m in members for w in wanted)
        return _yes_no(hit), f"{label}: {_shown(p.value)} ({'names' if hit else 'names none of'} {', '.join(c.value or ())})"
    number = float(p.value)
    state = number > float(c.value) if c.test == "above" else number < float(c.value)  # type: ignore[arg-type]
    return _yes_no(state), f"{label} {_shown(p.value)}, {c.test} {float(c.value):g} ({c.source}): {_yes_no(state)}"  # type: ignore[arg-type]


def _shown(value: Any) -> str:
    if isinstance(value, bool):
        return _yes_no(value)
    if isinstance(value, float):
        return f"{value:.3g}"
    if isinstance(value, frozenset):
        return ", ".join(sorted(value)) or "none"
    return str(value)


def evaluate(trigger: Trigger, props: Mapping[str, Prop]) -> tuple[State, list[str]]:
    """A trigger's state over the properties (core.yaml's evaluation): any is yes when one part is, no when all are; all
    is no when one part is, yes when all are; otherwise unknown. Returns the state and each condition in words."""
    if trigger.condition is not None:
        state, words = _condition(trigger.condition, props)
        return state, [words]
    results = [evaluate(p, props) for p in trigger.parts]
    states = [s for s, _w in results]
    words = [w for _s, ws in results for w in ws]
    if trigger.op == "any":
        return ("yes" if "yes" in states else "no" if all(s == "no" for s in states) else "unknown"), words
    return ("no" if "no" in states else "yes" if all(s == "yes" for s in states) else "unknown"), words


# --- 3. the ledger ---------------------------------------------------------------------------------------------------

RANK = {"required": 6, "usually_needed": 5, "conditional": 4, "to_ask": 3, "optional": 2, "not_needed": 1}
LEVEL_WORDS = {"required": "required", "usually_needed": "usually needed", "conditional": "required (its condition holds)",
               "to_ask": "applies if its condition holds", "optional": "optional", "not_needed": "not needed",
               "context": "context only"}
# The room's own requests for a compound input (assemble.COMPOUND), by the field they ask for, and the draft items that
# ask for the same value: such an item is not asked for twice
SAME_ASK: dict[str, tuple[str, ...]] = {
    "substance.mw": ("core.molecular_weight",), "substance.pka": ("core.pka",), "substance.logp": ("core.lipophilicity",),
    "adme.fu": ("core.fu_plasma", "fih.fu_species"), "adme.bp_ratio": ("core.blood_plasma_ratio",),
    "substance.permeability": ("fe.permeability", "vbe.permeability", "fih.permeability"),
    "substance.solubility": ("fe.solubility_vs_ph", "vbe.solubility_vs_ph", "fih.solubility"),
}


def _level(item: DraftItem, applies: State) -> str:
    if item.status == "CONDITIONAL":
        return {"yes": "conditional", "no": "not_needed"}.get(applies, "to_ask")
    return {"REQUIRED": "required", "USUALLY_NEEDED": "usually_needed", "OPTIONAL": "optional"}.get(item.status, "not_needed")


def _topics_of(item: DraftItem) -> set[str]:
    """The checklist topics an item's room fields belong to (a topic it names, the topics of its fields and tables)."""
    out: set[str] = set()
    for entry in item.room_fields:
        prefix, _, value = entry.partition(":")
        if prefix == "topic":
            out.add(value)
        elif prefix == "field":
            out |= {t for t, prefixes in TOPIC_FIELDS.items() if value.startswith(prefixes)}
        elif prefix == "table":
            out |= {t for t, kinds in TOPIC_TABLES.items() if value in kinds}
    return out


def context_topics(drafts: Drafts) -> frozenset[str]:
    """The topics only context-only material names (no item of any draft asks for data under them)."""
    used = {t for f in (drafts.core, *drafts.files.values()) for i in f.items for t in _topics_of(i)}
    return frozenset({t for i in drafts.context_only.items for t in _topics_of(i)} - used)


def context_checklist(card: QuestionCard | None, drafts: Drafts | None = None) -> dict[str, DraftItem]:
    """The question card's checklist items that ask only for context-only material (A6's fixed list asks every project
    for the manufacturing process): checklist id -> the context-only draft item it stands for."""
    drafts = drafts or load_drafts()
    topics = context_topics(drafts)
    out: dict[str, DraftItem] = {}
    for c in card.checklist if card else ():
        data = set(c.topics) - PAPERWORK
        if data and data <= topics:
            ctx = next((i for i in drafts.context_only.items if data & _topics_of(i)), None)
            if ctx is not None:
                out[c.id] = ctx
    return out


def _base(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _coverage(item: DraftItem, level: str, ev: Evidence, applies_words: str) -> dict[str, Any]:
    """Where the room covers an item: what satisfies it (facts, tables, topics, entered values) and its chips; the files
    searched when nothing does."""
    found: list[str] = []
    chips: list[Chip] = []
    entered = ev.entered or {}
    for entry in item.room_fields:
        prefix, _, value = entry.partition(":")
        if prefix == "field":
            got = ev.ok(value)
            kind = FIELD_TABLES.get(value, "")
            same = [t for t in ev.tables if kind and t.description.kind == kind and f"table:{kind}" not in item.room_fields]
            if got:
                found.append(f"{FIELDS.get(value, value)}: {len(got)} fact{'s' if len(got) > 1 else ''}")
                chips += [f.chip for f in got if f.chip]
            elif same:
                found.append(f"{FIELDS.get(value, value)}: {len(same)} {FIELD_TABLES[value].replace('_', ' ')} "
                             f"table{'s' if len(same) > 1 else ''}")
                chips += [c for t in same if (c := _table_chip(t))]
            elif value in entered:
                found.append(f"{FIELDS.get(value, value)}: entered by a person")
        elif prefix == "table":
            got_t = [t for t in ev.tables if t.description.kind == value]
            if got_t:
                found.append(f"{value.replace('_', ' ')} table{'s' if len(got_t) > 1 else ''}: {len(got_t)}")
                chips += [c for t in got_t if (c := _table_chip(t))]
        elif prefix == "topic":
            fields = TOPIC_FIELDS.get(value, ())
            kinds = TOPIC_TABLES.get(value, ())
            facts = [f for f in ev.facts if f.ok and fields and f.fact.field.startswith(fields)]
            tables = [t for t in ev.tables if t.description.kind in kinds]
            if facts or tables:
                found.append(f"{value.replace('_', ' ')}: {len(facts)} fact(s), {len(tables)} table(s)")
                chips += [f.chip for f in facts if f.chip] + [c for t in tables if (c := _table_chip(t))]
    chips = list(dict.fromkeys(chips))
    gap = bool(item.room_gap)
    if level == "context":
        text = ("kept as context: " + "; ".join(found) if found else
                "not in the delivery: kept as context when it comes, never asked for")
        return {"coverage": "context", "coverage_text": text, "found": tuple(found), "chips": tuple(chips[:8])}
    if level == "not_needed":
        text = f"not needed for this question: {applies_words}" if item.status == "CONDITIONAL" else \
            f"not needed for this question: {item.why}"
        return {"coverage": "not_needed", "coverage_text": text}
    if item.kind in ("activity", "system"):
        text = ("a modeller's task, stated in the analysis plan; never asked of the client" if item.kind == "activity" else
                f"from the platform ({item.default_provider.lower()}), never from the client's files")
        return {"coverage": "not_from_delivery", "coverage_text": text}
    if not item.room_fields:
        return {"coverage": "person_checks", "coverage_text": "the room cannot read this yet: a person checks it"}
    if found:
        if gap:
            return {"coverage": "found_in_part", "found": tuple(found), "chips": tuple(chips[:8]),
                    "coverage_text": "found in part: " + "; ".join(found) + ". The room cannot read all of this yet: a "
                                     "person checks it"}
        return {"coverage": "found", "coverage_text": "found: " + "; ".join(found), "found": tuple(found),
                "chips": tuple(chips[:8])}
    topics = _topics_of(item)
    used = [f for f in ev.files if f.triage is None or f.triage.purpose != "not_needed"]
    searched = [f.path for f in used if f.triage and set(f.triage.topics) & topics] or [
        f.path for f in used if f.triage is None or f.triage.purpose == "used"] or [f.path for f in ev.files]
    where = (f"{len(searched)} file{'s' if len(searched) != 1 else ''} searched: " + ", ".join(_base(p) for p in searched)
             if searched else "no file in the room yet")
    gap_words = " The room cannot read all of this yet: a person checks it too." if gap else ""
    if level == "to_ask":
        return {"coverage": "to_ask", "searched": tuple(searched),
                "coverage_text": f"applies if: {item.trigger_text} (not known from the delivery); not found, {where}"}
    if level == "optional":
        return {"coverage": "absent", "searched": tuple(searched),
                "coverage_text": f"not in the delivery ({where}); optional, so never asked for"}
    return {"coverage": "missing", "searched": tuple(searched), "coverage_text": f"missing: {where}.{gap_words}"}


def ledger(drafts: Drafts, apps: Sequence[Application], props: Mapping[str, Prop], ev: Evidence,
           context_asks: Mapping[str, Sequence[ChecklistItem]] | None = None) -> list[RequirementItem]:
    """The checklist for the chosen applications (the core items alone when none), each item once with its coverage.

    Several applications: each lists the core items it does not override and its own; an item and the core item it
    overrides are one input, and the strictest status across the applications wins (REQUIRED > USUALLY_NEEDED >
    CONDITIONAL that applies > CONDITIONAL not known > OPTIONAL > NOT_NEEDED), naming the applications that set it.
    The context-only items follow, never missing."""
    lists: list[tuple[str, tuple[DraftItem, ...]]] = [(a.label, drafts.items_for(a.file, a.subcontext)) for a in apps] or [
        ("the core items (every context of use)", drafts.core.items)]
    states: dict[str, tuple[State, list[str]]] = {}
    groups: dict[str, list[tuple[DraftItem, str, str]]] = {i.id: [] for i in drafts.core.items}
    for label, items in lists:
        for item in items:
            if item.id not in states:
                states[item.id] = evaluate(item.trigger, props) if item.trigger else ("", [])
            level = _level(item, states[item.id][0])
            for key in item.overrides or (item.id,):
                groups.setdefault(key, []).append((item, label, level))
    out: list[RequirementItem] = []
    seen: set[str] = set()
    every = len(lists) > 1
    for candidates in groups.values():
        if not candidates:
            continue
        best = max(RANK[level] for _i, _l, level in candidates)
        top = [(i, label, level) for i, label, level in candidates if RANK[level] == best]
        # the more specific item stands for the input: an application's own over the core's
        winner, _label, level = next((c for c in top if c[0].file != "core"), top[0])
        if winner.id in seen:
            continue
        seen.add(winner.id)
        by = tuple(dict.fromkeys(label for _i, label, _lv in top))
        if winner.file == "core" and every and len(by) == len(lists):
            by = ("every application (core)",)
        others = tuple(dict.fromkeys(f"{label}: {LEVEL_WORDS[lv]} ({i.id})" for i, label, lv in candidates
                                     if RANK[lv] < best))
        out.append(_entry(winner, level, states.get(winner.id, ("", [])), by, others, ev))
    for item in drafts.context_only.items:
        entry = _entry(item, "context", ("", []), ("every application",), (), ev)
        asked = [c for c in (context_asks or {}).get(item.id, ())]
        if asked:
            entry = entry.model_copy(update={"coverage_text": entry.coverage_text + "; the question card's checklist item "
                                             + ", ".join(f"“{c.label}”" for c in asked) + " is kept as context, not asked for"})
        out.append(entry)
    return out


def _entry(item: DraftItem, level: str, state: tuple[State, list[str]], by: tuple[str, ...], others: tuple[str, ...],
           ev: Evidence) -> RequirementItem:
    applies, words = state
    applies_words = "; ".join(words)
    if item.status == "CONDITIONAL":
        applies_words = {"yes": "its condition holds", "no": "its condition does not hold"}.get(applies, "not known") + \
            f" ({item.trigger_text.rstrip('.')}: {applies_words})"
    return RequirementItem(
        id=item.id, label=item.label, group=item.group, kind=item.kind, status=item.status, level=level,  # type: ignore[arg-type]
        applies=applies if item.status == "CONDITIONAL" else "",  # type: ignore[arg-type]
        trigger=item.trigger_text, trigger_state="; ".join(words), escalates=item.escalates, why=item.why,
        alternatives=item.alternatives, record_with=item.record_with, sources=item.sources, by=by, others=others,
        room_gap=bool(item.room_gap), note=item.note, **_coverage(item, level, ev, applies_words))


# --- 4. data requests ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ask:
    item: str
    area: str
    title: str
    why: str


def area_of(item: RequirementItem, drafts: Drafts | None = None) -> str:
    """The data request's letter (A formulation · B in vitro · C drug substance and disposition · D clinical) by the
    item's data category, else its group."""
    raw = (drafts or load_drafts()).item(item.id)
    category = raw.data_category if raw else "other"
    if category == "formulation":
        return "A"
    if category == "dissolution":
        return "B"
    if category in ("physchem", "binding", "in_vitro_adme", "urine_feces"):
        return "C"
    if category.startswith("clinical_") or category == "bioanalytical":
        return "D"
    return {"Formulation": "A", "Dissolution": "B", "Absorption": "B", "Phys-chem": "C", "Binding": "C",
            "Permeability": "C", "Elimination": "C", "Distribution": "C", "Transporters": "C", "DDI": "C"}.get(item.group, "D")


def asks(items: Sequence[RequirementItem], drafts: Drafts | None = None) -> list[Ask]:
    """The data requests the checklist makes: each missing item that is required here (REQUIRED, or CONDITIONAL with its
    condition holding) or usually needed (said so). Nothing not needed, inapplicable, not known, optional or context."""
    out = []
    for i in items:
        if i.coverage != "missing" or i.level not in ("required", "conditional", "usually_needed"):
            continue
        head = {"required": "Required", "conditional": "Required here (its condition holds)",
                "usually_needed": "Usually needed"}[i.level]
        why = f"{head} for {', '.join(i.by)}: {i.why.rstrip('.')}."
        if i.level == "usually_needed" and i.escalates:
            why += f" Required when: {i.escalates.rstrip('.')}."
        if i.alternatives:
            why += f" If it is not available: {'; '.join(i.alternatives)}."
        out.append(Ask(item=i.id, area=area_of(i, drafts), title=i.label, why=f"{why} {DRAFT_WORDS}"))
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def already_asked(ask: Ask, requests: Sequence[DataRequest]) -> DataRequest | None:
    """A request the room already makes for the same thing: the same item id or title, or the room's own request for
    the compound value the item asks for (`SAME_ASK`), or a draft's request for that same value."""
    same = {ask.item} | {i for ids in SAME_ASK.values() if ask.item in ids for i in ids}
    fields = {f for f, ids in SAME_ASK.items() if ask.item in ids}
    for r in requests:
        if r.checklist in same or _norm(r.title) == _norm(ask.title) or (r.checklist in fields and r.input):
            return r
    return None


# --- the whole -------------------------------------------------------------------------------------------------------


def requirements(card: QuestionCard | None, decision: RoomDecision | None, ev: Evidence,
                 drafts: Drafts | None = None) -> Requirements | None:
    """The checklist for the question as the page shows it; None without a question card."""
    if card is None:
        return None
    drafts = drafts or load_drafts()
    apps = chosen_applications(decision)
    props = properties(card, ev)
    asked: dict[str, list[ChecklistItem]] = {}
    for cid, ctx in context_checklist(card, drafts).items():
        asked.setdefault(ctx.id, []).extend(c for c in card.checklist if c.id == cid)
    items = ledger(drafts, apps, props, ev, asked)
    named = {c.property for a in apps for i in drafts.items_for(a.file, a.subcontext) if i.trigger
             for c in i.trigger.conditions()} if apps else {c.property for i in drafts.core.items if i.trigger
                                                            for c in i.trigger.conditions()}
    shown = []
    for name in sorted(named):
        d = drafts.properties[name]
        p = props.get(name)
        if p and (p.known or p.basis):
            basis = p.basis
        else:
            why = ("not read by code: a person answers" if d.how == "ask" else
                   "not known: it needs a cut-off the SME sets" if "SME" in d.determined_by and name not in _CODE_READS else
                   "not known from the delivery")
            basis = f"{why} ({d.determined_by.split('. ')[0].rstrip('.')})"
        shown.append(PropertyRead(name=name, label=_property_label(name), how=d.how,
                                  value=_shown(p.value) if p and p.known else "not known", known=bool(p and p.known),
                                  basis=basis, sources=p.chips if p else ()))
    read = read_applications(card)
    return Requirements(label=LABEL, version=drafts.version(), applications=tuple(a.label for a in apps),
                        chosen=bool(decision and decision.chosen), properties=tuple(shown), items=tuple(items),
                        read=tuple(ReadPhrase(application=a, label=_BY_ID[a].label, words=w) for a, w in read.items()))


def finding(req: Requirements | None) -> tuple[str, bool, bool]:
    """The section's line, whether it is in order, and whether it is empty."""
    if req is None:
        return "No question card yet: the checklist follows the question", True, True
    count: dict[str, int] = {}
    for i in req.items:
        count[i.coverage] = count.get(i.coverage, 0) + 1
    apps = " + ".join(req.applications) or "the core items only"
    # each item counted once: found in part is for a person to check, as the room cannot read all of it
    parts = [f"{count.get('found', 0)} found", f"{count.get('missing', 0)} missing"]
    if count.get("to_ask"):
        parts.append(f"{count['to_ask']} to ask")
    if count.get("person_checks") or count.get("found_in_part"):
        parts.append(f"{count.get('person_checks', 0) + count.get('found_in_part', 0)} for a person to check")
    line = (f"{apps}{'' if req.chosen else ' (as read from the question card)'}: {', '.join(parts)}; "
            f"{count.get('not_needed', 0)} not needed (draft requirements, UNVERIFIED)")
    ok = req.chosen and not count.get("missing") and not count.get("to_ask")
    return line, ok, False


__all__ = ["APPLICATIONS", "DECISION", "DRAFT_WORDS", "PHRASES", "SAME_ASK", "TOPIC_FIELDS", "TOPIC_TABLES", "Application",
           "Ask", "Evidence", "Prop", "already_asked", "applications_decision", "area_of", "asks", "chosen_applications",
           "context_checklist", "context_topics", "evaluate", "finding", "ledger", "properties", "read_applications",
           "requirements"]
