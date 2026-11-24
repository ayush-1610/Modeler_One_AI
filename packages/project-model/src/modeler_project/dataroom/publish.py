"""Send to the model (plan 2026-11-21 v2 §4, §5 step 9; plan 2026-11-24 §7, phase 4): the Data room's confirmed inputs
land in the stores the rest of the platform reads, each with its source, so Review & sign, Run and the reports work
unchanged.

- every compound input with a value (CPF id) and each product's release (form.<name>.type Weibull and its t50, shape
  and lag, fitted by code to the chosen profile) become evidence items, proposed and accepted under the publication;
- every study arm's mean profile in the chosen analysis set becomes an observed dataset (arithmetic mean ± SD and the
  geometric mean, N per time), its study record the arm's design, route, dose, water, food state, meals and individual.

Where each item is from (ICH M15), never a guess:
- a value read from the client's files: CLIENT_REPORT, provider CLIENT, its file, place and quote; one that only the
  delivery's literature or label files give: PUBLICATION, provider LITERATURE, the file as its citation;
- a value a person entered: ASSUMPTION, entered by hand (MANUAL), the person's reason in the note;
- a pH by convention (D4): ASSUMPTION, labelled "by convention, not stated (confirmed by …)", never the sponsor's;
- a release fitted by code: CLIENT_FILE, COMPUTED, with the profile, the fit function and its version, the equation and
  the engine check, as `modeler_project.dissolution_register` records them; a profile a Weibull curve does not
  describe (a plateau, a very rapid release) says so in its note (the SME decides: dissolution_similarity / MS-01);
- each dataset: its concentration file and place (`RoomStudy.sources`), and the analyte and matrix the files state.

What each arm's study record says:
- food state: the arm's own (its definition's words, else the study's statement), the condition at dosing; meals
  (`_place_meals`): one at or before the dose is the fed condition's and goes only on the fed arms; one after the dose
  is every arm's day and goes on every arm, fasted ones too, unless an arm's own definition ties it to that arm; a meal
  no rule places (a meal before the dose and no fed arm, a fed arm with meals only after the dose, meals with no time,
  fed arms naming different meals) blocks the send with what to decide. Every meal of a study takes the study's one
  meal decision's template (a known gap: a fed breakfast and later standard meals share it);
- route: oral, the one the room sends (a route stated otherwise blocks; one not stated is said);
- design: single dose; a multiple-dose study blocks ("the model is built from single-dose data"): its profiles are per
  day from each day's dose, and the regimen is free text, so no dose interval or count is mapped by guess;
- formulation: an immediate-release tablet (a capsule when the files say so) with its Weibull release; a modified-release
  product blocks (the MS-01 split classes it apart, PO-MR);
- individual: the population and sex chosen in the room, the age (and its range), weight and height of the demographics
  table, else as the synopsis states them; with no age stated the individual is left to Inputs (D-29: no silent
  30-year-old) and the note names the population and sex chosen; water not given is said, never filled in silently.

`plan_publication` builds and checks everything and writes nothing; `publish` writes it. Nothing is published while a
decision it depends on waits, an input it needs is Missing, or a study's arms are already in the project through
Delivery or Inputs (nothing is loaded twice): the plan lists what blocks it.

Sending again (R3): an item's id follows what is sent (its target or study and its content; never a chip's box or
text), so the same content is skipped (idempotent). A new item for a target or study the room sent before replaces the
earlier one: the earlier Data room item is rejected, "superseded by publication <id>", through the registers' own
decide functions (audited), so the latest publication is what Inputs and the model read. An item superseded earlier is
accepted again when a later send carries it again; one a person rejected elsewhere stays rejected (said in the notes).

What a send rested on (`publication_basis`) is kept, one file per publication, at
`<root>/<tenant>/projects/<project>/dataroom/publications/<publication id>.json` (`DataRoomStore.put_publication`), for
the plan and the MAP to read. Its shape (`publication_record`; format "dataroom-publication/1"):

    {"format": "dataroom-publication/1",
     "id": "pub-20261124T101500Z-3fa2c1",          # pub-<UTC time>-<6 random hex>
     "at": "2026-11-24T10:15:00+00:00", "by": "<user id>", "reason": "<why sent now>",
     "signature_id": "<Part 11 signature id>",     # "" when written without one
     "signed_record_sha256": "<sha256 of the record the signature covers>",
     "basis_sha256": "<sha256 of `basis`, canonical JSON: sort_keys, separators (',', ':'), UTF-8>",
     "basis": {
        "format": "dataroom-publication-basis/2",     # /2 added "room_basis"; a /1 basis has none
        "rules": "<the Data room rules' label and version>",
        "question": {"card": <QuestionCard as JSON> | null, "confirmed": bool, "confirmed_by": str, "confirmed_at": str},
        "applications": null | {"chosen": "<option id, e.g. pbbm_bridging_vbe+food_effect>", "by_person": bool,
                                "ids": [...], "labels": [...], "reason": str, "by": str, "at": str},
        "decisions": [{"id", "title", "chosen", "option", "suggested", "by_person": bool, "reason", "by", "at"}],
        "open_requests": [{"id", "area", "title", "why", "wording", "checklist", "input"}],      # status "open" only
        "nca_differ": [{"study_id", "subject", "period", "treatment", "metric", "difference_percent", "client"}],
        "nca_reproduction": [{"study_id", "settings": {"integration", "time_basis", "blq", "lambda_z"}, "told_apart",
                              "not_told", "compared", "passed", "explained", "investigate", "differ", "tiers",
                              "summary"}],                                   # `model.NcaReproduction` as JSON
        "blq": [{"study_id", "lloq", "unit", "analysis_set", "arithmetic_mean", "geometric_mean"}],
        "notes": ["<each non-blocking remark of the plan: the fed meal not given to a fasted arm, water not stated, …>"],
        "room_basis": <modeler_project.room_basis.RoomBasis as JSON> | null},   # what the brief, plan, MAP and VBE read
     "evidence": [{"id", "target", "value", "unit", "source_type", "provider", "extraction", "note"}],
     "datasets": [{"id", "study_id", "n", "route", "design", "formulation", "food_state", "meals", "water_ml_per_kg",
                   "demographics", "demographics_choice", "analyte", "matrix", "note"}],
     "written": {"evidence": int, "datasets": int, "skipped": int, "superseded": int},
     "superseded": {"evidence": [ids], "datasets": [ids]}}

The Part 11 signature of the send (`modeler_api.dataroom_api.publish_dataroom`) covers the publication id and
`basis_sha256` beside the ids sent.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from modeler_project.dataroom import checklist
from modeler_project.dataroom.assemble import (
    MEDIA_CONVENTION,
    POPULATION_LABELS,
    WATER_DEFAULT,
    convention_words,
    meal_times,
    release_remark,
    stated_demographic,
)
from modeler_project.dataroom.invitro import named_in
from modeler_project.dataroom.model import Arm, Chip, DataRoomView, DissolutionView, InputRow, RoomDecision, RoomStudy, Value
from modeler_project.dataroom.rules import load_rules
from modeler_project.datasets import ObservedDataset, Origin, Series, check_dataset
from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction, SourceRef, SourceType
from modeler_project.workspace import Workspace

SUPERSEDED = "superseded by publication"
FORMAT = "dataroom-publication/1"
BASIS_FORMAT = "dataroom-publication-basis/2"
_LITERATURE_TOPICS = {"literature", "label"}          # as `assemble` tells a literature file (its triage's topics)
_SENT_PREFIXES = ("ev-dr", "ds-dr")                     # the ids "Send to the model" gives


class Publication(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: tuple[EvidenceItem, ...] = ()
    datasets: tuple[ObservedDataset, ...] = ()
    blocked: tuple[str, ...] = ()         # what keeps the publication from being sent, in words
    notes: tuple[str, ...] = ()           # what is sent otherwise than the files might suggest, in words (never blocks)


def from_data_room(item_id: str) -> bool:
    """Whether an evidence item or dataset was sent from the Data room."""
    return item_id.startswith(_SENT_PREFIXES)


def _digest(content: Any) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()


def _evidence_id(item: EvidenceItem) -> str:
    """What the item sends, never where a chip's box or text fell: the same content is the same id."""
    what = item.model_dump(mode="json", include={"target", "value", "unit", "source_type", "provider", "extraction",
                                                 "conditions", "purpose", "note"})
    return f"ev-dr{_digest([what, item.source.doc_sha256])[:10]}"


def _dataset_id(dataset: ObservedDataset) -> str:
    what = dataset.model_dump(mode="json", exclude={"id", "proposed_at", "proposed_by", "state", "decided_by",
                                                    "decision_reason", "flags"})
    return f"ds-dr{_digest(what)[:10]}"


def _source(chips: tuple[Chip, ...]) -> tuple[SourceRef, str, Extraction]:
    if not chips:
        return SourceRef(), "", Extraction.COMPUTED
    c = chips[0]
    page = int(c.part[1:]) if re.fullmatch(r"p\d+", c.part) else None
    locator = c.ref or f"{c.part} line {c.line}" + (f" cell {c.cell}" if c.cell else "")
    kind = Extraction.CELL if c.ref else (Extraction.TABLE if c.cell else Extraction.TEXT)
    return SourceRef(doc_sha256=c.sha256 or None, page=page, locator=locator, title=c.file), c.text, kind


def slug(name: str) -> str:
    """A product's CPF formulation name: its words joined ("Exampleamide 100 mg (test)" -> Exampleamide_100_mg_test)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:60] or "product"


def literature_files(view: DataRoomView) -> set[str]:
    """The delivery's literature and label files (by their triage), as `assemble` tells them."""
    return {f.path for f in view.files if f.triage and set(f.triage.topics) & _LITERATURE_TOPICS}


def _evidence(row: InputRow, target: str, value: float | str, *, by: str, note: str, literature: set[str],
              chips: tuple[Chip, ...] | None = None, convention: str = "", conditions: dict[str, str] | None = None,
              flags: tuple[str, ...] = ()) -> EvidenceItem:
    """One evidence item with its true source (see the module docstring)."""
    chips = row.sources if chips is None else chips
    if row.status == "entered":
        # a person's own value: their reason is its source, and no document stands behind it here
        source_type, provider, extraction = SourceType.ASSUMPTION, "CLIENT", Extraction.MANUAL
        source, quote = SourceRef(title="entered in the Data room", locator=row.label), ""
        note = f"{note}; entered by a person: {row.note}" if row.note else f"{note}; entered by a person"
    elif convention:
        source_type, provider, extraction = SourceType.ASSUMPTION, "CLIENT", Extraction.COMPUTED
        source, quote, _kind = _source(chips)
        note = f"{note}; {convention}"
    else:
        # a client file's chip first: a value the client's files and a label both state is the client's
        ordered = tuple(sorted(chips, key=lambda c: c.file in literature))
        source, quote, kind = _source(ordered)
        if row.status == "calculated":
            source_type, provider, extraction = SourceType.CLIENT_FILE, "CLIENT", Extraction.COMPUTED
        elif ordered and all(c.file in literature for c in ordered):
            source_type, provider, extraction = SourceType.PUBLICATION, "LITERATURE", kind
            source = source.model_copy(update={"title": f"{source.title} (literature in the delivery)"})
        else:
            source_type, provider, extraction = SourceType.CLIENT_REPORT, "CLIENT", kind
    item = EvidenceItem(id="ev-dr", target=target, value=value, unit=row.unit or None, source_type=source_type,
                        source=source, quote=quote, extraction=extraction, provider=provider,  # type: ignore[arg-type]
                        purpose="model_building", proposed_by=by, note=note, conditions=conditions or {}, flags=flags)
    return item.model_copy(update={"id": _evidence_id(item)})


def _fit_record(profile: DissolutionView, convention: RoomDecision | None) -> tuple[dict[str, str], tuple[str, ...]]:
    """The conditions a Weibull evidence item records (as `dissolution_register.propose_release_model` does): the
    profile, the fit function and its version, the equation, the fit's quality, and the engine check; an unconfirmed
    function is flagged so."""
    from pbpk_domain.dissolution import ENGINE_CHECK

    fit = profile.weibull
    medium = profile.medium or "medium not stated"
    if profile.ph_by_convention and profile.ph is not None:
        medium += f" ({convention_words(profile.medium, profile.ph, convention)})"
    elif profile.ph is not None:
        medium += f" (pH {profile.ph:g})"
    conditions = {"profile": f"{profile.product or profile.batch} · batch {profile.batch} · {profile.id}",
                  "medium": medium, "function": str(fit.get("function_version") or ""),
                  "equation": str(fit.get("equation") or ""),
                  "fit": f"n = {fit.get('n_points')} points, RMSE {fit.get('rmse_percent')} %, SE t50 {fit.get('se_t50')}, "
                         f"SE shape {fit.get('se_shape')}"}
    confirmed = bool(fit.get("engine_confirmed"))
    if confirmed:
        conditions["engine check"] = ENGINE_CHECK
    flags = () if confirmed else ("unconfirmed: the Weibull equation is not yet compared with PK-Sim's own release curve",)
    return conditions, flags


# --- the study record, arm by arm -------------------------------------------------------------------------------------

_ORAL = re.compile(r"(?i)\boral(?:ly)?\b|\bper\s*os\b|\bp\.\s?o\.|\bpo\b|by mouth|swallow")
_NOT_ORAL = re.compile(r"(?i)intravenous|\bi\.\s?v\.|\biv\b|infusion|bolus|subcutaneous|intramuscular|inhal|"
                       r"transdermal|topical|rectal|sublingual|buccal|nasal")
_MULTIPLE = re.compile(r"(?i)\bmultiple[- ]dos|\brepeated?[- ]dos|\bonce[- ]daily\b|\btwice[- ]daily\b|"
                       r"\b(?:three|four) times (?:a|per) day\b|\bb\.?i\.?d\b|\bt\.?i\.?d\b|\bq\.?d\b|\bq\d+h\b|"
                       r"\bsteady[- ]state\b")
_SINGLE = re.compile(r"(?i)\bsingle\b")
# a product that is modified release (the split classes it PO-MR; the room fits an immediate-release tablet): its release
# or coating fact's own word ("extended", "delayed" …), or, in its name, definition or dosage form, "… release" or the
# abbreviation ("ER", "XR" …): "a modified formulation" alone is a reformulation, not a release
_MODIFIED_WORD = re.compile(r"(?i)\bextended\b|\bmodified\b|\bdelayed\b|\bsustained\b|\bprolonged\b|\bcontrolled\b|"
                            r"\benteric\b|gastro[- ]?resistant")
_MODIFIED_RELEASE = re.compile(r"(?i)\b(?:extended|modified|delayed|sustained|prolonged|controlled)[- ]release\b|"
                               r"\benteric[- ]coat|gastro[- ]?resistant|(?-i:\b(?:ER|XR|MR|SR|CR|DR|XL)\b)")
_CAPSULE = re.compile(r"(?i)\bcapsules?\b")


def _fact(study: RoomStudy, field: str) -> Value | None:
    return next((v for v in study.facts if v.key.split("[")[0] == field), None)


def _route(study: RoomStudy) -> tuple[str, str]:
    """("oral", a note) or ("", why it blocks)."""
    fact = _fact(study, "study.route")
    if fact is None:
        return "oral", (f"{study.study_id}: the route is not stated in the files: sent as oral, the route of the tablets "
                        "whose dissolution gives each arm's release; say so if it is not")
    text = f"{fact.as_written} {fact.value if isinstance(fact.value, str) else ''}"
    if _ORAL.search(text) and not _NOT_ORAL.search(text):
        return "oral", ""
    return "", (f"{study.study_id}: the route is {fact.as_written!r}: only oral studies are sent from the Data room (each "
                "arm's release is an oral tablet's Weibull fit; an IV study needs its infusion time and no release)")


def _multiple_dose(study: RoomStudy) -> str:
    """Why the study is a multiple-dose one ("" when it is not)."""
    if any(p.code == "MULTIPLE_DOSE" for p in study.problems):
        return "its data have a profile per day"
    for field in ("study.regimen", "study.design"):
        fact = _fact(study, field)
        if fact is not None and _MULTIPLE.search(fact.as_written) and not _SINGLE.search(fact.as_written):
            return f"the files say {fact.as_written!r}"
    return ""


def _about(key: str, product: str) -> bool:
    subject = key.split("[", 1)[1].rstrip("]") if "[" in key else ""
    return not subject or named_in(subject, [product]) == product or named_in(product, [subject]) == subject


def _product_words(view: DataRoomView, arm: Arm) -> tuple[list[str], list[str]]:
    """What the files say of an arm's product: (its release and coating facts, its name, definition, dosage form and
    name facts); a fact about it, or about no product in particular."""
    release, named = [], [arm.product, arm.meaning]
    for v in view.products:
        field = v.key.split("[")[0]
        if not _about(v.key, arm.product):
            continue
        if field in ("product.release", "product.coating"):
            release.append(v.as_written)
        elif field in ("product.dosage_form", "product.name"):
            named.append(v.as_written)
    return [w for w in release if w], [w for w in named if w]


def _modified_release(view: DataRoomView, arm: Arm) -> str:
    """The words that make an arm's product modified release, as written ("" when none do)."""
    release, named = _product_words(view, arm)
    return next((w for w in release if _MODIFIED_WORD.search(w)), "") or next(
        (w for w in named if _MODIFIED_RELEASE.search(w)), "")


def _meal_kind(text: str) -> str:
    low = text.lower()
    if "high" in low and "fat" in low:
        return "a high-fat meal"
    if re.search(r"standard|low[- ]fat|light|moderate", low):
        return "a standard meal"
    return ""


def _meals(rows: list[InputRow], sid: str) -> tuple[list[dict[str, Any]], str]:
    """The study's meals as PK-Sim meal events (the harvested template the meal decision chose, at each time read, in
    hours after the dose), and why they cannot be read ("" when they can): a meal with no time cannot be given to the
    arms it was served to."""
    meals: list[dict[str, Any]] = []
    for r in rows:
        if r.block == "event" and r.owner == sid:
            if r.value is None:
                return [], (f"{sid}: its meal times could not be read ({r.note}): say when each meal was served, so each "
                            "goes on the arms it was served to")
            for t in re.findall(r"-?\d+(?:\.\d+)?", str(r.value)):
                meals.append({"time_h": float(t), "template": r.name, "name": r.name.split(": ", 1)[-1]})
    return sorted(meals, key=lambda m: m["time_h"]), ""


def _hours(meals: list[dict[str, Any]]) -> str:
    return ", ".join(f"{m['time_h']:g}" for m in meals) + " h"


def _place_meals(sid: str, arms: list[Arm], food: dict[str, str | None], meals: list[dict[str, Any]]
                 ) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[str]]:
    """Each arm's meals, what is said about them, and what keeps them from being placed. "Fasted" is the condition at
    dosing; the protocol's later meals are every arm's day:
    - a meal at or before the dose (time ≤ 0) is the fed condition's: it goes only on the fed arms;
    - a meal after the dose goes on every arm, fasted ones too, unless the files tie it to some arms (an arm's own
      definition names its time): then only on those;
    - a meal before the dose with no fed arm, or a fed arm with meals only after the dose (its fed meal not given), cannot
      be placed: the send is blocked with what to decide."""
    before = [m for m in meals if m["time_h"] <= 0]
    after = [m for m in meals if m["time_h"] > 0]
    own = {a.treatment: set(meal_times(a.meaning) or ()) for a in arms}
    placed: dict[str, list[dict[str, Any]]] = {}
    said: list[str] = []
    blocked: list[str] = []
    if before and not any(food[a.treatment] == "fed" for a in arms):
        blocked.append(f"{sid}: a meal at {_hours(before)}, at or before the dose, is a fed condition's, and no arm is fed: "
                       "decide which arm was dosed fed (its definition), or when the meal was served")
    for arm in arms:
        fed = food[arm.treatment] == "fed"
        if fed and after and not before:
            blocked.append(f"{sid} arm {arm.treatment}: fed, but the meals given are all after the dose ({_hours(after)}): "
                           "say when its fed meal was served (at or before the dose)")
        tied = [m for m in after if not any(m["time_h"] in times for times in own.values())
                or m["time_h"] in own[arm.treatment]]
        placed[arm.treatment] = (before if fed else []) + tied
        if not fed and before:
            said.append(f"{sid} arm {arm.treatment}: fasted at dosing, so the fed condition's meal at {_hours(before)} is "
                        "not given to it" + (f"; the meals after the dose ({_hours(tied)}) are" if tied else ""))
        if len(tied) < len(after):
            said.append(f"{sid} arm {arm.treatment}: the meal at {_hours([m for m in after if m not in tied])} is another "
                        "arm's (its definition names it), not given to this one")
    return placed, said, blocked


def _individual(study: RoomStudy, get: dict[str, InputRow]) -> tuple[dict[str, Any] | None, str, str]:
    """(the study record's demographics, a note, why it blocks). The population and sex chosen in the room go on the
    record with the age (mean and range), weight and height of the demographics table, else as the files state them;
    with no age stated, none (D-29: no silent default) and the note names what was chosen."""
    sid = study.study_id
    population, sex = get.get("Population"), get.get("Gender")
    age, weight, height = get.get("Age"), get.get("Weight"), get.get("Height")
    for row in (age, weight, height):
        if row is not None and row.status == "conflict":
            return None, "", f"{sid}: the files disagree on its {row.name.lower()}: enter the value to use"
    pop = population.value if population and isinstance(population.value, str) and population.value else None
    gender = sex.value if sex and sex.value in ("MALE", "FEMALE") else None
    chosen = f"{POPULATION_LABELS.get(pop, pop) if pop else 'no population'}, {gender.lower() if gender else 'sex not known'}"
    if age is None or not isinstance(age.value, float):
        span = stated_demographic(study, "age").span
        return None, (f"{sid}: no mean age is stated" + (f" (only the range {span[0]:g}–{span[1]:g} years)" if span else "")
                      + f", so the individual chosen here ({chosen}) is not set on the study record: Inputs asks for "
                      "the demographics (D-29); give them there, or choose the healthy adult default"), ""
    if pop is None:
        return None, "", f"{sid}: the population is not chosen"
    if gender is None:
        return None, "", f"{sid}: the individual's sex is not known"
    demographics: dict[str, Any] = {"population": pop, "sex": gender, "age_years": age.value}
    table = {v.key.rsplit(".", 1)[-1]: v.value for v in study.facts if ".demographics." in v.key}
    span = ((table["age_min"], table["age_max"]) if isinstance(table.get("age_min"), float | int)
            and isinstance(table.get("age_max"), float | int) else stated_demographic(study, "age").span)
    if span and 0 < span[0] < span[1]:
        demographics["age_min"], demographics["age_max"] = float(span[0]), float(span[1])
    if weight and isinstance(weight.value, float):
        demographics["weight_kg"] = weight.value
    if height and isinstance(height.value, float):
        demographics["height_cm"] = height.value
    return demographics, "", ""


def _analyte_matrix(study: RoomStudy, products: list[str]) -> tuple[str, str, list[str]]:
    """The dataset's analyte and matrix as the files state them, and what is said about them. An analyte the files
    name by the drug of the card's products (no metabolite words) is the parent; another is kept as written, so Inputs
    tells it from the modelled compound. A matrix not stated stays plasma, and the note says so."""
    notes = []
    analyte, matrix = "parent", "plasma"
    fact = _fact(study, "study.analyte")
    if fact is not None:
        text = fact.as_written
        drug_words = {w for p in products for w in re.findall(r"[a-z]{4,}", p.lower())} - {
            "tablet", "tablets", "capsule", "capsules", "test", "reference", "product", "formulation", "reformulated",
            "clinical", "commercial", "film", "coated", "oral", "solution", "suspension"}
        metabolite = re.search(r"(?i)metabolite|\bM\d+\b|glucuronide|N-oxide|desmethyl|demethyl|hydroxy", text)
        if metabolite or not (drug_words & set(re.findall(r"[a-z]{4,}", text.lower()))):
            analyte = text
            notes.append(f"the analyte is {text!r} as the files write it")
        else:
            notes.append(f"the analyte as written: {text!r} (the drug: the parent)")
    else:
        notes.append("the analyte is not stated: the parent drug")
    mfact = _fact(study, "study.matrix")
    if mfact is not None:
        matrix = mfact.as_written
    else:
        notes.append("the matrix is not stated: plasma")
    return analyte, matrix, notes


def _dataset_source(study: RoomStudy) -> tuple[SourceRef, str]:
    """The arm's dataset's source: its concentration file and place (a sheet as `Sheet!line`, the template's way, a page
    as its number), and every file it is read from."""
    chips = study.sources
    if not chips:
        return SourceRef(), ""
    first = chips[0]
    sheets = [f"{c.part.split(':', 1)[1]}!{c.line}" for c in chips if c.sha256 == first.sha256 and c.part.startswith("sheet:")]
    page = int(first.part[1:]) if re.fullmatch(r"p\d+", first.part) else None
    locator = "; ".join(sheets) or f"{first.part} from line {first.line}"
    files = list(dict.fromkeys(c.file for c in chips))
    read = "; ".join(f"{c.file} ({c.part}, from line {c.line})" for c in chips)
    return SourceRef(doc_sha256=first.sha256 or None, page=page, locator=locator, title=", ".join(files)), read


def _dataset(study: RoomStudy, arm: Arm, set_name: str, *, view: DataRoomView, rows: list[InputRow], by: str,
             formulation_name: str, formulation: str, route_note: str, food: str, meals: list[dict[str, Any]],
             notes: list[str]) -> tuple[ObservedDataset | None, str]:
    sid, treatment = study.study_id, arm.treatment
    owner = f"{sid} · {treatment}"
    profile = next((p for p in study.profiles if p.treatment == treatment and p.analysis_set == set_name), None)
    if profile is None or profile.n_subjects == 0:
        return None, f"{owner}: no subject of the chosen set has this arm's profile"
    get = {r.name: r for r in rows if r.owner in (sid, owner)}
    dose = get.get("InputDose")
    if dose is None or not isinstance(dose.value, float):
        return None, f"{owner}: the dose is missing"
    demographics, individual_note, why = _individual(study, get)
    if why:
        return None, why
    said = [n for n in (route_note, individual_note) if n]
    water = get.get("Volume of water/body weight")
    water_ml = water.value if water and isinstance(water.value, float) else None
    if water_ml is None:
        said.append(f"{owner}: " + (water.note if water and water.note else f"the water with the dose is not given: {WATER_DEFAULT}"))
    analyte, matrix, about = _analyte_matrix(study, [p.name for p in (view.question.products if view.question else ())])
    source, read = _dataset_source(study)
    points = profile.points
    times = tuple(p.time_h for p in points)
    arith = tuple(None if (p.mean is None or (p.n_geo == 0 and p.mean == 0)) else p.mean for p in points)
    n = profile.n_subjects
    record = {"study_id": f"{sid}-{treatment}", "n": n, "design": "SD", "crossover": len(study.periods) > 1,
              "route": "oral", "dose_mg": dose.value, "formulation": formulation, "formulation_name": formulation_name,
              "food_state": food, "meals": meals, "water_ml_per_kg": water_ml,
              "demographics": demographics, "statistic": "mean_sd", "n_timepoints": len(times)}
    if study.lloq is not None:
        record["lloq"] = study.lloq
    series = (Series(name="arithmetic mean", statistic="arithmetic_mean", times=times, values=arith,
                     error=tuple(p.sd for p in points), error_kind="SD", n=n,
                     n_at=tuple(p.n for p in points) if len({p.n for p in points}) > 1 else None),
              Series(name="geometric mean", statistic="geometric_mean", times=times, values=tuple(p.geomean for p in points),
                     n=n, n_at=tuple(p.n_geo for p in points) if len({p.n_geo for p in points}) > 1 else None))
    unit = study.concentration_unit.replace("mL", "ml").replace("L", "l")
    label = next((s.label for s in study.sets if s.name == set_name), set_name)
    how = (f"Data room: the mean of the {label.lower()} ({n} subjects in this arm); below the LLOQ counted 0 in the "
           "arithmetic mean and left out of the geometric mean")
    note = "; ".join([how, *about, *([f"read from {read}"] if read else []), *said])
    dataset = ObservedDataset(
        id="ds-dr", kind="profile", study=record, analyte=analyte, matrix=matrix, time_unit="h", unit=unit, series=series,
        origin=Origin.CLIENT, extraction="TABLE", source=source, provider="CLIENT", purpose="model_building",
        proposed_by=by, demographics_choice="entered" if demographics else None, note=note)
    try:
        checked = check_dataset(dataset)
    except ValueError as exc:
        return None, f"{owner}: {exc}"
    notes.extend(said)
    return checked.model_copy(update={"id": _dataset_id(checked)}), ""


_BLOCKING_STUDY = ("TIME_UNIT_NOT_STATED", "UNIT_NOT_STATED", "SAMPLE_CONFLICT", "NO_CONCENTRATIONS")


def _already_loaded(ws: Workspace, study: RoomStudy, found: list[ObservedDataset]) -> str:
    """Why the study's arms are already in the project ("" when they are not): a dataset that Delivery landed or that
    Inputs holds from the same concentration file (not rejected), or a signed Delivery confirmation that covers them
    (the rule of the legacy readers' guard, `intake_review.delivery_covers`). Nothing is loaded twice."""
    from modeler_project import dataset_register
    from modeler_project.intake_landing import is_delivery_dataset
    from modeler_project.intake_review import delivery_covers

    files = {c.sha256: c.file for c in study.sources if c.sha256}
    for d in dataset_register.datasets(ws):
        if from_data_room(d.id) or d.state is EvidenceState.REJECTED or d.source.doc_sha256 not in files:
            continue
        how = "landed by a Delivery confirmation" if is_delivery_dataset(d) else "read on Inputs"
        return (f"{study.study_id}: its concentrations ({files[d.source.doc_sha256]}) are already in the project as dataset "
                f"{d.id} (study {d.study.get('study_id')}, {how}): nothing is loaded twice. Use that one, or reject it "
                "there with the reason before sending it from here")
    covered = delivery_covers(ws, found)
    if covered is not None:
        one, confirmation = covered
        return (f"{study.study_id}: the signed Delivery confirmation {confirmation.id} already covers its concentrations "
                f"({one.source.title}): nothing is loaded twice. It is in the project already; to change it, correct it "
                "on Delivery and confirm there again")
    return ""


def plan_publication(view: DataRoomView, *, by: str, ws: Workspace | None = None) -> Publication:
    """What would be sent and what blocks it; nothing is written. With the project's workspace (`ws`), a study already
    in the project through Delivery or Inputs blocks too."""
    blocked: list[str] = []
    notes: list[str] = []
    waiting = [d.title for d in view.decisions if not d.chosen]
    if waiting:
        blocked.append("decisions waiting: " + "; ".join(waiting))
    if not view.question_confirmed:
        blocked.append("the question card is not confirmed")
    rows = list(view.inputs)
    literature = literature_files(view)
    decisions = {d.id: d for d in view.decisions}
    chosen = {d.id: d.chosen or d.suggested for d in view.decisions}
    convention = decisions.get(MEDIA_CONVENTION)
    ref_solubility = None
    if chosen.get("solubility-ref") and view.solubility:
        try:
            ref_solubility = view.solubility[int(chosen["solubility-ref"].split("-")[1])]
        except (IndexError, ValueError):
            ref_solubility = None
    evidence: list[EvidenceItem] = []
    for row in rows:
        if row.block != "compound":
            continue
        if row.status == "conflict":
            blocked.append(f"{row.label}: the sources disagree; choose one (enter it) before sending")
        elif row.value is not None and row.status != "missing":
            if not isinstance(row.value, float):
                blocked.append(f"{row.label}: {row.value!r} is not one number")
                continue
            by_convention = (row.name == "phys.solubility.ref_ph" and row.status != "entered" and ref_solubility is not None
                             and ref_solubility.ph_by_convention)
            evidence.append(_evidence(row, row.name, row.value, by=by, note=f"Data room: {row.label}", literature=literature,
                                      convention=convention_words(ref_solubility.medium, row.value, convention)
                                      if by_convention and ref_solubility is not None else ""))
    names = {r.name for r in rows if r.block == "compound" and r.value is not None}
    if "phys.solubility.ref" in names and "phys.solubility.ref_ph" not in names:
        blocked.append("the reference solubility has no pH: choose a solubility with its pH, or enter the pH")
    formulations: dict[str, str] = {}
    fits: dict[str, tuple[dict[str, str], tuple[str, ...], str, tuple[Chip, ...]]] = {}
    rules = load_rules()
    for row in rows:
        if row.block != "formulation":
            continue
        name = slug(row.owner)
        if row.name == "Formulation_Tablet_Weibull":
            if chosen.get(f"release-model:{row.owner}") == "particles":
                blocked.append(f"{row.owner}: particle dissolution needs the particle size and solubility entered as "
                               "inputs; send it with the Weibull release, or enter them")
                continue
            fitted = [r for r in rows if r.block == "formulation" and r.owner == row.owner and r.name in (
                "Dissolution time (50% dissolved)", "Dissolution shape") and isinstance(r.value, float)]
            if len(fitted) < 2:
                blocked.append(f"{row.owner}: its Weibull fit did not give t50 and shape (too few time points)")
                continue
            profile = next((d for d in view.dissolution if d.id == chosen.get(f"release:{row.owner}")), None)
            if profile is None:
                blocked.append(f"{row.owner}: the chosen dissolution profile is not in the room")
                continue
            conditions, flags = _fit_record(profile, convention)
            remark = release_remark(profile, rules)
            if remark:
                notes.append(f"{row.owner}: {remark}")
            fits[row.owner] = (conditions, flags, remark, profile.sources[:1])
            formulations[row.owner] = name
            evidence.append(_evidence(row.model_copy(update={"status": "calculated"}), f"form.{name}.type", "Weibull", by=by,
                                      note=f"Data room: {row.owner}" + (f"; {remark}" if remark else ""), literature=literature,
                                      chips=profile.sources[:1], conditions=conditions))
            continue
        key = {"Dissolution time (50% dissolved)": "t50", "Dissolution shape": "shape", "Lag time": "lag"}.get(row.name)
        if key and isinstance(row.value, float) and row.owner in formulations:
            conditions, flags, remark, chips = fits[row.owner]
            evidence.append(_evidence(row, f"form.{name}.weibull.{key}", row.value, by=by, literature=literature,
                                      note=f"Data room: {row.note}" + (f"; {remark}" if remark and remark not in row.note else ""),
                                      chips=row.sources or chips, conditions=conditions, flags=flags))
    from modeler_project.evidence import assess

    for item in evidence:
        flags = assess(item).flags
        if item.unit and any(f.startswith("needs_conversion") for f in flags):
            blocked.append(f"{item.target}: {item.value} {item.unit} cannot be converted to PK-Sim's unit; enter it in "
                           "PK-Sim's unit")
    datasets: list[ObservedDataset] = []
    for study in view.studies:
        sid = study.study_id
        bad = [p.message for p in study.problems if p.code in _BLOCKING_STUDY]
        if bad:
            blocked.append(f"{sid}: " + "; ".join(bad))
            continue
        if why := _multiple_dose(study):
            blocked.append(f"{sid}: multiple-dose studies are not sent yet: the model is built from single-dose data ({why})")
            continue
        route, route_note = _route(study)
        if not route:
            blocked.append(route_note)
            continue
        set_name = chosen.get(f"analysis-set:{sid}", "modeling")
        arm_codes = {a.treatment for a in study.arms}
        treatments = {p.treatment for p in study.profiles}
        if treatments - arm_codes:
            blocked.append(f"{sid}: what treatment {', '.join(sorted(treatments - arm_codes))} stands for is not "
                           "given (its product is unknown)")
        sent = [a for a in study.arms if a.treatment in treatments]
        food_rows = {r.owner: r for r in rows if r.name == "Food state" and (r.owner == sid or r.owner.startswith(f"{sid} · "))}
        food = {a.treatment: (food_rows.get(f"{sid} · {a.treatment}") or food_rows.get(sid)) for a in sent}
        meals, meal_problem = _meals(rows, sid)
        if meal_problem:
            blocked.append(meal_problem)
            continue
        states = {a.treatment: str(food[a.treatment].value) if food[a.treatment] is not None else None  # type: ignore[union-attr]
                  for a in sent}
        fed = [a for a in sent if states[a.treatment] == "fed"]
        kinds = {a.treatment: k for a in fed if (k := _meal_kind(a.meaning))}
        if any(m["time_h"] <= 0 for m in meals) and len(set(kinds.values())) > 1:
            blocked.append(f"{sid}: its fed arms name different meals (" + "; ".join(f"{t}: {k}" for t, k in sorted(kinds.items()))
                           + "), and the study's one meal decision would give every fed arm the same: decide which meal "
                           "each fed arm had (a meal per arm is not sent yet)")
            continue
        placed, said, unplaced = _place_meals(sid, sent, states, meals)
        if unplaced:
            blocked += unplaced
            continue
        notes += said
        found: list[ObservedDataset] = []
        for arm in sent:
            if not arm.product:
                blocked.append(f"{sid} arm {arm.treatment}: its product is not known ({arm.meaning or 'no meaning given'})")
                continue
            if modified := _modified_release(view, arm):
                blocked.append(f"{sid} arm {arm.treatment}: {arm.product} is a modified-release product ({modified!r}): "
                               "modified release is not sent yet (the room fits an immediate-release tablet's Weibull "
                               "release, and the MS-01 split classes modified-release studies apart, PO-MR)")
                continue
            if arm.product not in formulations:
                blocked.append(f"{sid} arm {arm.treatment}: {arm.product} has no release input (no dissolution "
                               "profile of it was read); its data request asks for one")
                continue
            state = food[arm.treatment]
            if state is None or state.value not in ("fed", "fasted"):
                blocked.append(f"{sid} arm {arm.treatment}: the study does not say fed or fasted")
                continue
            kind = "ir_capsule" if any(_CAPSULE.search(w) for w in _product_words(view, arm)[1]) else "ir_tablet"
            got, why = _dataset(study, arm, set_name, view=view, rows=rows, by=by, formulation_name=formulations[arm.product],
                                formulation=kind, route_note=route_note, food=str(state.value),
                                meals=placed[arm.treatment], notes=notes)
            if got is None:
                blocked.append(why)
            else:
                found.append(got)
        if ws is not None and found and (why := _already_loaded(ws, study, found)):
            blocked.append(why)
            continue
        datasets += found
    return Publication(evidence=tuple(evidence), datasets=tuple(datasets), blocked=tuple(dict.fromkeys(blocked)),
                       notes=tuple(dict.fromkeys(notes)))


# --- what the send rested on --------------------------------------------------------------------------------------------


def publication_basis(view: DataRoomView, plan: Publication, *, question: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a send rests on, for the plan and the MAP to read (the shape is in the module docstring). `question`: the
    store's record of the question card (who confirmed it, when). `room_basis` is the reading of the room the brief,
    the plan, the MAP and the VBE panel take (`modeler_project.room_basis`), as it stood when sent: after a send they
    read it from here, so a decision changed in the room later reaches them only with the next send."""
    # imported here: room_basis reads this module (`slug`)
    from modeler_project.room_basis import basis_from_view

    room = basis_from_view(view)
    apps = next((d for d in view.decisions if d.id == checklist.DECISION), None)
    in_force = checklist.chosen_applications(apps)
    chosen = {d.id: d.chosen or d.suggested for d in view.decisions}

    def option(d: RoomDecision) -> str:
        pick = d.chosen or d.suggested
        return next((o.label for o in d.options if o.id == pick), pick)

    confirmed = view.question_confirmed
    return {
        "format": BASIS_FORMAT,
        "rules": view.rules,
        "question": {"card": view.question.model_dump(mode="json") if view.question else None, "confirmed": confirmed,
                     "confirmed_by": str((question or {}).get("by", "")) if confirmed else "",
                     "confirmed_at": str((question or {}).get("at", "")) if confirmed else ""},
        "applications": None if apps is None else {
            "chosen": apps.chosen or apps.suggested, "by_person": apps.chosen is not None, "ids": [a.id for a in in_force],
            "labels": [a.label for a in in_force], "reason": apps.reason, "by": apps.by, "at": apps.at},
        "decisions": [{"id": d.id, "title": d.title, "chosen": d.chosen or d.suggested, "option": option(d),
                       "suggested": d.suggested, "by_person": d.chosen is not None, "reason": d.reason, "by": d.by,
                       "at": d.at} for d in view.decisions if d.id != checklist.DECISION],
        "open_requests": [{"id": r.id, "area": r.area, "title": r.title, "why": r.why, "wording": r.wording,
                           "checklist": r.checklist, "input": r.input} for r in view.requests if r.status == "open"],
        "nca_differ": [{"study_id": s.study_id, "subject": n.subject, "period": n.period, "treatment": n.treatment,
                        "metric": metric, "difference_percent": n.differences.get(metric), "client": n.client.get(metric)}
                       for s in view.studies for n in s.nca for metric, tier in sorted(n.tiers.items()) if tier == "differ"],
        "nca_reproduction": [{"study_id": s.study_id, **s.nca_reproduction.model_dump(mode="json")}
                             for s in view.studies if s.nca_reproduction is not None],
        "blq": [{"study_id": s.study_id, "lloq": s.lloq, "unit": s.concentration_unit,
                 "analysis_set": chosen.get(f"analysis-set:{s.study_id}", "modeling"),
                 "arithmetic_mean": "below the LLOQ counted as 0",
                 "geometric_mean": "below the LLOQ left out (quantifiable values only)"} for s in view.studies],
        "notes": list(plan.notes),
        "room_basis": room.model_dump(mode="json") if room is not None else None,
    }


def basis_sha256(basis: dict[str, Any]) -> str:
    """The sha256 of a basis as stored: canonical JSON (sorted keys, no spaces), UTF-8."""
    return _digest(basis)


def publication_id(at: datetime | None = None) -> str:
    """A new publication's id: its UTC time and 6 random hex digits (two sends of the same content in one second are two
    publications, each signed)."""
    return f"pub-{(at or datetime.now(UTC)):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def publication_record(pub_id: str, *, basis: dict[str, Any], plan: Publication, written: dict[str, Any], by: str,
                       reason: str, signature_id: str = "", signed_record: str = "") -> dict[str, Any]:
    """The publication's file (`DataRoomStore.put_publication`); the shape is in the module docstring."""
    return {
        "format": FORMAT, "id": pub_id, "at": datetime.now(UTC).isoformat(timespec="seconds"), "by": by, "reason": reason,
        "signature_id": signature_id,
        "signed_record_sha256": hashlib.sha256(signed_record.encode()).hexdigest() if signed_record else "",
        "basis_sha256": basis_sha256(basis), "basis": basis,
        "evidence": [{"id": e.id, "target": e.target, "value": e.value, "unit": e.unit, "source_type": e.source_type.value,
                      "provider": e.provider, "extraction": e.extraction.value, "note": e.note} for e in plan.evidence],
        "datasets": [{"id": d.id, **{k: d.study.get(k) for k in ("study_id", "n", "route", "design", "formulation",
                                                                    "food_state", "meals", "water_ml_per_kg",
                                                                    "demographics")},
                      "demographics_choice": d.demographics_choice, "analyte": d.analyte, "matrix": d.matrix,
                      "note": d.note} for d in plan.datasets],
        "written": {k: written.get(k, 0) for k in ("evidence", "datasets", "skipped", "superseded")},
        "superseded": {"evidence": list(written.get("superseded_evidence", [])),
                       "datasets": list(written.get("superseded_datasets", []))},
    }


# --- sending ---------------------------------------------------------------------------------------------------------------


def publish(ws: Workspace, view: DataRoomView, *, by: str, reason: str, publication: str = "") -> dict[str, Any]:
    """Write the publication (refused while anything blocks it): each new item proposed and accepted; the same content
    skipped; an earlier Data room item of a target or study sent again rejected, superseded by this publication.
    Returns the counts and the ids superseded (`superseded_evidence`, `superseded_datasets`)."""
    from modeler_project import dataset_register, evidence_register
    from modeler_project.artifacts import ArtifactKind

    plan = plan_publication(view, by=by, ws=ws)
    if plan.blocked:
        raise ValueError("not sent to the model: " + " · ".join(plan.blocked))
    pub = publication or "(no id)"
    sent = f"sent from the Data room (publication {pub}): {reason}"
    written: dict[str, Any] = {"evidence": 0, "datasets": 0, "skipped": 0, "superseded": 0,
                               "superseded_evidence": [], "superseded_datasets": []}
    for item in plan.evidence:
        current = ws.latest(ArtifactKind.EVIDENCE, item.id)
        if current is not None:
            held = EvidenceItem.from_content(current.content)
            if held.state is EvidenceState.REJECTED and held.decision_reason.startswith(SUPERSEDED):
                evidence_register.decide(ws, item.id, state=EvidenceState.ACCEPTED, reason=f"sent again: {sent}", by=by)
                written["evidence"] += 1
            else:
                written["skipped"] += 1
            continue
        proposed = evidence_register.propose(ws, item, actor=by, value_in_quote=bool(item.quote) or None)
        # a value with no unit (a pH, a shape factor) is its own PK-Sim value: the person sending it accepts it as such;
        # a value whose unit code cannot convert was refused by the plan
        unitless = proposed.value_pksim is None and isinstance(item.value, int | float) and not item.unit
        evidence_register.decide(ws, item.id, state=EvidenceState.ACCEPTED, reason=sent, by=by,
                                 value_pksim=float(item.value) if unitless else None)  # type: ignore[arg-type]
        written["evidence"] += 1
    for dataset in plan.datasets:
        held_ds = dataset_register.dataset(ws, dataset.id)
        if held_ds is not None:
            if held_ds.state is EvidenceState.REJECTED and held_ds.decision_reason.startswith(SUPERSEDED):
                dataset_register.decide_dataset(ws, dataset.id, state=EvidenceState.ACCEPTED, reason=f"sent again: {sent}",
                                                by=by)
                written["datasets"] += 1
            else:
                written["skipped"] += 1
            continue
        dataset_register.propose_dataset(ws, dataset, actor=by)
        dataset_register.decide_dataset(ws, dataset.id, state=EvidenceState.ACCEPTED, reason=sent, by=by)
        written["datasets"] += 1
    # what this send replaces: the Data room's earlier items of the same targets and studies (nothing else is touched)
    superseded = f"{SUPERSEDED} {pub}"
    targets, ids = {e.target for e in plan.evidence}, {e.id for e in plan.evidence}
    for old in evidence_register.items(ws):
        if from_data_room(old.id) and old.target in targets and old.id not in ids and old.state is not EvidenceState.REJECTED:
            evidence_register.decide(ws, old.id, state=EvidenceState.REJECTED, reason=superseded, by=by)
            written["superseded_evidence"].append(old.id)
    studies, ds_ids = {str(d.study["study_id"]) for d in plan.datasets}, {d.id for d in plan.datasets}
    for old_ds in dataset_register.datasets(ws):
        if (from_data_room(old_ds.id) and str(old_ds.study.get("study_id")) in studies and old_ds.id not in ds_ids
                and old_ds.state is not EvidenceState.REJECTED):
            dataset_register.decide_dataset(ws, old_ds.id, state=EvidenceState.REJECTED, reason=superseded, by=by)
            written["superseded_datasets"].append(old_ds.id)
    written["superseded"] = len(written["superseded_evidence"]) + len(written["superseded_datasets"])
    return written
