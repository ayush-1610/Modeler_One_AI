"""The Data room put together (plan 2026-11-21 v2 §5-§8): from the agents' descriptions and quoted facts, code reads
and checks every value, joins them across files, applies the rules, and proposes the decisions, the data requests, the
simulation plan and the PK-Sim inputs. Nothing is invented: what no file gives is Missing, with a data request.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from modeler_intake.room_specs import Extraction, QuestionCard
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom.clinical import study_view, subject_id
from modeler_project.dataroom.extract import check_fact, parse_number, read_table
from modeler_project.dataroom.invitro import (
    batch_products,
    composition_rows,
    dissolution_views,
    f2_pairs,
    solubility_rows,
)
from modeler_project.dataroom.model import (
    Arm,
    CheckedFact,
    Chip,
    DataRequest,
    DataRoomView,
    Decision,
    DissolutionView,
    FileView,
    InputRow,
    Option,
    PlanRow,
    Problem,
    ReadTable,
    Section,
    StudyView,
    Value,
)
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
# Which checklist topics a fact field or a table kind covers
_TOPIC_FIELDS = {"clinical_design": ("study.design", "study.id", "study.regimen"), "dosing_and_meals": ("study.dose", "study.fed",
                 "study.fasting", "study.meal", "study.water"), "clinical_demographics": ("study.age", "study.weight", "study.sex"),
                 "clinical_disposition": ("study.completed", "study.excluded", "study.n_"), "bioanalysis": ("study.lloq",
                 "study.analyte", "study.matrix"), "be_statistics": ("study.be_result",), "drug_substance": ("substance.",),
                 "adme": ("adme.",), "composition": ("product.composition",), "solubility": ("substance.solubility",),
                 "particle_size": ("substance.particle_size",), "label": ("adme.", "substance.")}
_TOPIC_TABLES = {"clinical_concentrations": ("concentrations",), "clinical_pk": ("pk_parameters",),
                 "clinical_demographics": ("demographics",), "clinical_disposition": ("disposition",),
                 "dissolution": ("dissolution",), "composition": ("composition",), "solubility": ("solubility",),
                 "particle_size": ("particle_size",), "be_statistics": ("be_statistics",), "drug_substance": ("physchem",)}
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
            groups[(f.fact.field, _norm(f.fact.subject or f.fact.product))].append(f)
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


_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{0,2}|\d{1,2})\s*[=:]\s*([^;,\n]+)")


def _arms(facts: Sequence[CheckedFact], question: QuestionCard | None) -> list[Arm]:
    """The study's treatment codes and what each stands for: one fact per code (its subject the code), or one sentence
    defining several ("B = test product; A = reference product"). A code's product is the fact's product, else the
    question card's only product of the role its meaning names (reference, test), shown as such."""
    out: dict[str, Arm] = {}
    by_role: dict[str, list[str]] = defaultdict(list)
    for p in (question.products if question else ()):
        by_role[p.role].append(p.name)
    for f in facts:
        pairs = [(f.fact.subject.strip(), f.fact.value.strip())] if f.fact.subject.strip() else [
            (m.group(1), m.group(2).strip()) for m in _CODE.finditer(f.fact.value)]
        for code, meaning in pairs:
            product = f.fact.product if f.fact.subject.strip() else ""
            if not product:
                role = next((r for r in ("reference", "reformulated", "test") if r in meaning.lower()), "")
                product = by_role[role][0] if role and len(by_role[role]) == 1 else ""
            role = next((p.role for p in (question.products if question else ()) if p.name == product), "")
            out.setdefault(code, Arm(treatment=code, meaning=meaning, product=product, role=role, source=f.chip))
    return sorted(out.values(), key=lambda a: a.treatment)


def _decision(decisions: Mapping[str, Mapping[str, str]], d: Decision) -> Decision:
    made = decisions.get(d.id)
    if made and made.get("chosen") in {o.id for o in d.options}:
        return d.model_copy(update={"chosen": made["chosen"], "reason": made.get("reason", ""), "by": made.get("by", ""),
                                    "at": made.get("at", "")})
    return d


def _pick(d: Decision) -> str:
    return d.chosen or d.suggested


def _first(facts: Sequence[CheckedFact], field: str, subject: str = "") -> CheckedFact | None:
    got = [f for f in facts if f.ok and f.fact.field == field and (not subject or not f.fact.subject
                                                                    or _same_study(f.fact.subject, subject))]
    return got[0] if got else None


def assemble(inputs: Inputs, *, rules: Rules | None = None) -> DataRoomView:
    rules = rules or load_rules()
    by_path = {f.path: f for f in inputs.files}
    triage = {f.path: f.triage for f in inputs.files if f.triage}
    literature_files = {p for p, t in triage.items() if t and set(t.topics) & _LITERATURE_TOPICS}
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
    for f in facts:
        if not f.ok:
            problems.append(Problem(code="FACT_REFUSED", message=f"{f.fact.field} = {f.fact.value!r} ({f.fact.file}): {f.problem}"))
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
    adme = _values(facts, "adme.", FIELDS, literature_files, rules)
    products = _values(facts, "product.", FIELDS, literature_files, rules) + _values(facts, "batch.", FIELDS, literature_files, rules)
    entered = {v.key: v for v in inputs.entered}

    # --- clinical ---------------------------------------------------------------------------------------------------
    study_ids: list[str] = []
    for t in by_kind["concentrations"]:
        sid = t.description.about or t.description.constants.get("study", "") or "study"
        if not any(_same_study(sid, s) for s in study_ids):
            study_ids.append(sid)
    studies: list[StudyView] = []
    decisions: list[Decision] = []
    for sid in study_ids:
        def mine(kind: str, sid: str = sid) -> list[ReadTable]:
            return [t for t in by_kind[kind] if not t.description.about or _same_study(t.description.about, sid)
                    or len(study_ids) == 1]

        sfacts = [f for f in facts if f.fact.field.startswith("study.") and (not f.fact.subject or len(study_ids) == 1
                                                                              or _same_study(f.fact.subject, sid))]
        arms = _arms([f for f in sfacts if f.ok and f.fact.field == "study.treatment_code"], question)
        study_values = _values([f for f in sfacts if f.fact.field != "study.treatment_code"], "study.", FIELDS,
                               literature_files, rules)
        view = study_view(sid, concentrations=mine("concentrations"), pk_tables=mine("pk_parameters"), facts=sfacts,
                          arms=arms, study_values=study_values, rules=rules)
        sets = {s.name: s for s in view.sets}
        options = [Option(id=name, label=f"{sets[name].label}: {len(sets[name].subjects)} subjects", detail=sets[name].rule)
                   for name in ("modeling", "client_statistical", "completed", "dosed") if name in sets]
        if options:
            decisions.append(_decision(inputs.decisions, Decision(
                id=f"analysis-set:{sid}", title=f"Analysis set for {sid}'s observed profiles",
                question="Which subjects make the observed mean profiles the model is compared with?", options=tuple(options),
                suggested="modeling", why="; ".join(f"subject {s}: {r}" for s, r in sorted(
                    view.excluded.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0) if "LLOQ" in r) or
                "the completers with evaluable profiles in every period")))
        dem = _demographics(mine("demographics"), sets["modeling"].subjects if "modeling" in sets else ())
        ethnicity = _first(sfacts, "study.ethnicity")
        guess = next((db for word, db in _ETHNICITY if ethnicity and word in ethnicity.fact.value.lower()), "European_ICRP_2002")
        decisions.append(_decision(inputs.decisions, Decision(
            id=f"population:{sid}", title=f"Population for {sid}",
            question="Which PK-Sim population database stands for the study's subjects?",
            options=tuple(Option(id=p, label=p) for p in POPULATIONS), suggested=guess,
            why=(f"the study's subjects are {ethnicity.fact.value}" if ethnicity else "no ethnicity found: the reference European")
            + ("; no Indian population exists in PK-Sim yet (backlog): the Asian database is the closest" if ethnicity and
               "indian" in ethnicity.fact.value.lower() else ""), evidence=(ethnicity.chip,) if ethnicity and ethnicity.chip else ())))
        meal = _first(sfacts, "study.meal_composition") or _first(sfacts, "study.fed") or _first(sfacts, "study.meal_times")
        if meal:
            high_fat = "high" in meal.fact.value.lower() and "fat" in meal.fact.value.lower()
            decisions.append(_decision(inputs.decisions, Decision(
                id=f"meal:{sid}", title=f"Meal template for {sid}",
                question="Which PK-Sim meal stands for the study's meals?",
                options=(Option(id="standard", label=MEAL_STANDARD), Option(id="high_fat", label=MEAL_HIGH_FAT)),
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
    f2s = f2_pairs(diss, roles)
    composition = composition_rows(by_kind["composition"])
    strength = _first(facts, "product.strength") or _first(facts, "study.dose")
    dose = strength.number if strength else None
    medium_volume = next((d.volume_ml for d in diss if d.volume_ml), None)
    solubility, found = solubility_rows(by_kind["solubility"], dose_mg=dose, medium_volume_ml=medium_volume, rules=rules)
    problems += found
    for product in sorted({d.product or d.batch for d in diss}):
        views = [d for d in diss if (d.product or d.batch) == product]
        qc = next((d for d in views if "qc" in d.medium.lower()), None)
        decisions.append(_decision(inputs.decisions, Decision(
            id=f"release:{product}", title=f"Release of {product}",
            question="Which dissolution profile gives the product's release in the model (a Weibull fit to it)?",
            options=tuple(Option(id=d.id, label=f"{d.medium or 'medium not stated'} · batch {d.batch}",
                                 detail=f"t50 {d.weibull.get('t50_min')} min, shape {d.weibull.get('shape')}"
                                 + (" · levels off below 100 %" if d.plateau else "")) for d in views),
            suggested=(qc or views[0]).id,
            why="the medium the client uses for quality control" if qc else "the first profile; compare the media",
            evidence=tuple(c for d in views for c in d.sources[:1]))))

    if solubility:
        water = next((r for r in solubility if "water" in r.medium.lower()), None)
        decisions.append(_decision(inputs.decisions, Decision(
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
            decisions.append(_decision(inputs.decisions, Decision(
                id=f"release-model:{product}", title=f"Release model for {product}",
                question="The chosen profile levels off below 100 %. How should the model release the drug?",
                options=(Option(id="weibull", label="Weibull fitted to the profile as measured",
                                detail=f"t50 {view.weibull.get('t50_min')} min, shape {view.weibull.get('shape')}: it creeps "
                                "towards 100 % after the last time"),
                         Option(id="particles", label="Particle dissolution from the particle size and the solubility",
                                detail="the plateau is then the solubility limit in the medium; needs d50 and solubility vs pH")),
                suggested="weibull", why=f"the highest mean is {max(view.mean):.0f} % at {view.times_min[-1]:g} min",
                evidence=view.sources[:1])))
    chosen = {d.id: _pick(d) for d in decisions}

    # --- data requests -------------------------------------------------------------------------------------------------
    requests: list[DataRequest] = []

    def request(area: str, title: str, why: str, checklist: str = "") -> None:
        n = sum(1 for r in requests if r.area == area) + 1
        rid = f"{area}-{n:02d}"
        edit = inputs.request_edits.get(rid, {})
        wording = edit.get("wording") or inputs.writing.get("requests", {}).get(title, "")
        requests.append(DataRequest(id=rid, area=area, title=title, why=why, wording=wording,  # type: ignore[arg-type]
                                    status=edit.get("status", "open"), checklist=checklist))  # type: ignore[arg-type]

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
                request(item.area, item.label, item.why or "needed for the question and not found in the delivery", item.id)
    for view in studies:
        for s, why in view.excluded.items():
            if "LLOQ" in why:
                request("D", f"Subject {s} of {view.study_id}: every concentration below the LLOQ",
                        "confirm the dose was taken and the samples assayed; until then the subject is out of the modeling set")
        for p in view.problems:
            if p.code in ("DOSED_DIFFERS", "COMPLETERS_DIFFER"):
                request("D", f"{view.study_id}: subject counts", p.message)
        if any(p.code == "NCA_DIFFERS" for p in view.problems):
            request("D", f"{view.study_id}: actual sampling times",
                    "a few of the client's AUC or Tmax values differ from ours at the nominal times; the actual times explain it")
    for d in diss:
        for p in d.problems:
            if p.code in ("MEAN_ROW_DIFFERS", "RSD_ROW_DIFFERS"):
                request("B", f"Dissolution {d.batch} in {d.medium}: the summary row", p.message)
    written = {(d.ph, _norm(d.medium)): d.medium for d in diss}
    tested = {(d.ph, _norm(d.medium)) for d in diss if roles.get(d.product) not in ("reference", None, "")}
    with_ref = {(d.ph, _norm(d.medium)) for d in diss if roles.get(d.product) == "reference"}
    for ph, medium in sorted(tested - with_ref, key=lambda x: (x[0] or 0, x[1])):
        if roles and any(r == "reference" for r in roles.values()):
            request("B", f"Reference product dissolution in {written.get((ph, medium)) or f'pH {ph:g}'}",
                    "the test product was tested in this medium and the reference was not: no comparison is possible")
    for key, label, field, _unit in COMPOUND:
        word = label.split(" (")[0].lower()
        asked = any(word in r.title.lower() or field in r.checklist for r in requests)
        found = any(v.key.startswith(field) for v in substance + adme) or (key == "phys.solubility.ref" and solubility)
        if not found and key not in entered and not asked:
            request("C", label, "a compound input of the model, not in the delivery: from the client, or from literature (marked so)",
                    field)

    # --- PK-Sim inputs ---------------------------------------------------------------------------------------------------
    inputs_rows: list[InputRow] = []
    for key, name, field, unit in COMPOUND:
        if key in entered:
            v = entered[key]
            inputs_rows.append(InputRow(block="compound", name=key, label=name, value=v.value, unit=v.unit, status="entered",
                                        note=v.note))
            continue
        got = next((v for v in substance + adme if v.key.split("[")[0] == field), None)
        if got is None and key == "phys.solubility.ref" and solubility and chosen.get("solubility-ref"):
            row = solubility[int(chosen["solubility-ref"].split("-")[1])]
            inputs_rows.append(InputRow(block="compound", name=key, label=label_of(key), value=row.solubility_mg_ml, unit="mg/ml",
                                        status="sponsor", sources=row.sources, decision="solubility-ref", note=row.as_written))
            inputs_rows.append(InputRow(block="compound", name="phys.solubility.ref_ph", label="Reference pH", value=row.ph,
                                        status="sponsor" if row.ph is not None else "missing", sources=row.sources,
                                        decision="solubility-ref"))
            continue
        value, note = (got.value, "") if got else (None, "not in the delivery: literature or a data request")
        if got and key == "bind.fu" and isinstance(value, float) and value > 1:
            value, note = round(1 - value / 100, 6), f"from {got.as_written} % bound"
        inputs_rows.append(InputRow(block="compound", name=key, label=name, value=value, unit=got.unit if got else unit,
                                    status=got.status if got else "missing", sources=got.sources if got else (), note=note))
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
        members = sets[set_name].subjects if set_name in sets else ()
        population = chosen.get(f"population:{sid}", "European_ICRP_2002")
        inputs_rows.append(InputRow(block="individual", owner=sid, name="Population", label="Population database",
                                    value=population, status="calculated", decision=f"population:{sid}"))
        dem = {v.key.rsplit(".", 1)[-1]: v for v in view.facts if ".demographics." in v.key}
        for k, label, unit in (("age_mean", "Age", "year(s)"), ("weight_mean", "Weight", "kg"), ("height_mean", "Height", "cm")):
            if k in dem:
                inputs_rows.append(InputRow(block="individual", owner=sid, name=label, label=f"{label} (mean)",
                                            value=dem[k].value, unit=unit, status="calculated", note=dem[k].rule))
            else:
                inputs_rows.append(InputRow(block="individual", owner=sid, name=label, label=f"{label} (mean)", unit=unit,
                                            status="missing", note="no demographics table read"))
        sex = next((v for v in view.facts if v.key.startswith("study.sex")), None)
        inputs_rows.append(InputRow(block="individual", owner=sid, name="Gender", label="Sex",
                                    value=sex.as_written if sex else None, status=sex.status if sex else "missing",
                                    sources=sex.sources if sex else ()))
        dose_v = next((v for v in view.facts if v.key.startswith("study.dose")), None)
        water = next((v for v in view.facts if v.key.startswith("study.water")), None)
        weight = dem.get("weight_mean")
        for arm in view.arms or tuple(Arm(treatment=t) for t in sorted({n.treatment for n in view.nca})):
            owner = f"{sid} · {arm.treatment}"
            inputs_rows.append(InputRow(block="protocol", owner=owner, name="ApplicationType", label="Route", value="Oral",
                                        status="sponsor" if (r := next((v for v in view.facts if v.key.startswith("study.route")),
                                                                       None)) else "missing",
                                        sources=r.sources if r else ()))
            inputs_rows.append(InputRow(block="protocol", owner=owner, name="InputDose", label="Dose",
                                        value=dose_v.value if dose_v else None, unit=(dose_v.unit or "mg") if dose_v else "mg",
                                        status=dose_v.status if dose_v else "missing", sources=dose_v.sources if dose_v else ()))
            if water and isinstance(water.value, float) and weight and isinstance(weight.value, float):
                inputs_rows.append(InputRow(block="protocol", owner=owner, name="Volume of water/body weight",
                                            label="Water with the dose", value=round(water.value / weight.value, 3), unit="ml/kg",
                                            status="calculated", sources=water.sources,
                                            note=f"{water.as_written} ÷ the mean weight {weight.value} kg"))
            n = len([s for s in members if any(r.subject == s and r.treatment == arm.treatment for r in view.nca)])
            inputs_rows.append(InputRow(block="observed", owner=owner, name="ObservedData",
                                        label=f"Mean profile, {sets[set_name].label if set_name in sets else set_name}",
                                        value=f"arithmetic mean ± SD and geometric mean, N = {n}",
                                        unit=view.concentration_unit, status="calculated", decision=f"analysis-set:{sid}"))
            role = arm.role or ""
            plan.append(PlanRow(formulation=arm.product or arm.meaning or arm.treatment,
                                condition=f"{sid}, {'fed' if any(v.key.startswith('study.fed') for v in view.facts) else 'fasted'}"
                                + (f", {dose_v.as_written}" if dose_v else ""),
                                observed=f"{sid} arm {arm.treatment} (N = {n})",
                                role="calibration" if role == "reference" else "verification",
                                why="the reference product's observed profile sets the model" if role == "reference"
                                else "the test product's profile checks the model built on the reference"))
        meal = chosen.get(f"meal:{sid}")
        times = next((v for v in view.facts if v.key.startswith("study.meal_times")), None)
        if meal:
            inputs_rows.append(InputRow(block="event", owner=sid, name=MEAL_HIGH_FAT if meal == "high_fat" else MEAL_STANDARD,
                                        label="Meal", value=times.as_written if times else None, unit="h after the dose",
                                        status=times.status if times else "missing", sources=times.sources if times else (),
                                        decision=f"meal:{sid}"))
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
                                role="prediction", why="no clinical data: the model predicts its exposure"))

    # --- sections --------------------------------------------------------------------------------------------------------
    written = inputs.writing.get("findings", {})

    def section(sid: str, title: str, finding: str, ok: bool, empty: bool) -> Section:
        return Section(id=sid, title=title, finding=written.get(sid) or finding,
                       status="empty" if empty else ("ok" if ok else "attention"))

    n_ocr = sum(len(f.ocr_pages) for f in inputs.files)
    open_requests = [r for r in requests if r.status == "open"]
    sections = [
        section("files", "Files", f"{len(inputs.files)} files read" + (f", {n_ocr} scanned pages read by our OCR" if n_ocr else ""),
                all(f.state in ("read", "partly_read") for f in inputs.files), not inputs.files),
        section("substance", "Drug substance", f"{len(substance)} properties found", not any(v.status == "conflict" for v in substance),
                not substance),
        section("adme", "ADME and disposition", f"{len(adme)} facts found", True, not adme),
        section("formulation", "Formulation", f"{len(composition)} components, {sum(1 for c in composition if c.changed)} changed",
                True, not composition),
        section("solubility", "Solubility", f"{len(solubility)} media", True, not solubility),
        section("dissolution", "Dissolution", f"{len(diss)} profiles; {sum(1 for d in diss if d.very_rapid)} release ≥ 85 % "
                "within 15 min", not any(d.problems for d in diss), not diss),
        section("clinical", "Clinical studies", "; ".join(
            f"{s.study_id}: {len(next((x.subjects for x in s.sets if x.name == 'modeling'), ()))} subjects in the modeling set"
            for s in studies), not any(p.severity == "error" for s in studies for p in s.problems), not studies),
        section("decisions", "Decisions", f"{sum(1 for d in decisions if not d.chosen)} waiting", all(d.chosen for d in decisions),
                not decisions),
        section("requests", "Data requests", f"{len(open_requests)} open", not open_requests, not requests),
        section("inputs", "PK-Sim inputs", f"{sum(1 for r in inputs_rows if r.status != 'missing')} of {len(inputs_rows)} filled",
                not any(r.status == "missing" for r in inputs_rows), not inputs_rows),
    ]
    return DataRoomView(rules=rules.label(), files=tuple(inputs.files), question=question,
                        question_confirmed=inputs.question_confirmed, sections=tuple(sections), substance=tuple(substance),
                        adme=tuple(adme), products=tuple(products), composition=tuple(composition), solubility=tuple(solubility),
                        dissolution=tuple(diss), f2=tuple(f2s), studies=tuple(studies), decisions=tuple(decisions),
                        requests=tuple(requests), plan=tuple(plan), inputs=tuple(inputs_rows), problems=tuple(problems))


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
