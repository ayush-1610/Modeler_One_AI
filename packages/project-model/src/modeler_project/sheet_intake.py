"""Each data sheet of a client's workbook read by code when the file arrives (plan 2026-11-05 §3.1, build C2; the owner,
2026-11-05: "the agent must recognise, clean and bring everything into the project").

Code's first reading of the sheet (`modeler_intake.sheet_form.suggest`, 11 of 11 layouts of the evaluation set) is kept
on the file as a draft. What it reads, it quotes; what the sheet does not say, it leaves:
- a draft that needs nothing more is **saved at once**, through the same path as the sheet reader's "Save these data":
  its datasets (or dissolution records) wait on Inputs, in their study or product, until a person confirms them;
- a draft that needs facts the sheet does not state (the number of subjects, the dosage form, what the study is for)
  waits on its study's card, its points drawn, and asks for them there; a document's fact for the same study is
  offered, with its quote. Answered, it is saved like any other reading.

A study's facts are never guessed: a draft is saved only with every fact the study record needs (MS-01 §3.1), as
stated in the sheet or given by a person. Nothing here loads data into the project; the confirmation on Inputs does.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from modeler_intake.cleaning import record as cleaning_record
from modeler_intake.grid import SheetGrid, WorkbookGrid
from modeler_intake.recipe_review import MappingReview, RecipeProposal, review_proposal
from modeler_intake.sheet_form import SheetForm, suggest, to_proposal
from modeler_project import Workspace
from modeler_project.documents import DocumentLibrary

PK = ("PK_INDIVIDUAL", "PK_SUMMARY")
READ = (*PK, "DISSOLUTION")
CODE = "code"

# what a draft still needs, in a person's words (the sheet reader's "Still to fill in", `SheetReader.tsx`)
NEED_LABEL: dict[str, str] = {
    "study_id": "the study it belongs to", "dose": "the dose", "route": "the route", "n": "the number of subjects",
    "formulation": "the dosage form", "food_state": "fasted or fed", "purpose": "what the study is for",
    "infusion_time_min": "the infusion time (min)", "product": "the product", "role": "the product's role",
    "medium": "the medium", "batch": "the batch", "value_columns": "the value columns", "time_column": "the time column",
}
CONSTANT_ANSWERS = ("study_id", "dose", "dose_unit", "route", "formulation", "food_state", "product", "role", "medium", "batch")
STUDY_ANSWERS = ("n", "purpose", "infusion_time_min", "design", "population_type")
PURPOSES = ("model_building", "external_validation", "application_verification")
FORMULATIONS = ("solution", "suspension", "ir_tablet", "ir_capsule", "mr", "other")
ROUTES = ("oral", "iv_bolus", "iv_infusion")
ROLES = ("TEST", "RLD", "REFERENCE", "OTHER")


class SheetIntakeError(ValueError):
    """A reading that cannot be saved, with what to do."""


def _positive(value: Any) -> bool:
    try:
        return float(str(value).replace(",", ".")) > 0
    except (TypeError, ValueError):
        return False


def needs(form: SheetForm) -> list[str]:
    """What the study record or the product needs that the reading does not give yet."""
    c, st, out = form.constants, form.study, []
    if form.kind == "concentration_time":
        if not (c.get("study_id") or "").strip():
            out.append("study_id")
        if not _positive(c.get("dose")):
            out.append("dose")
        if c.get("route") not in ROUTES:
            out.append("route")
        if not _positive(st.get("n")):
            out.append("n")
        if c.get("route") == "oral":
            out += [k for k in ("formulation", "food_state") if not c.get(k)]
        if not st.get("purpose"):
            out.append("purpose")
        if c.get("route") == "iv_infusion" and not _positive(st.get("infusion_time_min")):
            out.append("infusion_time_min")
    else:
        out += [k for k in ("product", "role", "medium", "batch") if not (c.get(k) or "").strip()]
    if not form.value_columns:
        out.append("value_columns")
    if form.layout == "times_down" and not form.time_column:
        out.append("time_column")
    return out


def _request(form: SheetForm) -> tuple[SheetForm, dict[str, Any]]:
    """The form and the study facts as the sheet reader sends them on "Save these data" (`SheetReader.body`)."""
    if form.kind != "concentration_time":
        return form, {}
    c, st = dict(form.constants), form.study
    n = int(float(st["n"]))
    if form.statistic != "individual" and not form.n_column:
        c["n"] = str(n)
    facts: dict[str, Any] = {"n": n, "design": st.get("design") or "SD", "crossover": st.get("crossover") in ("true", "yes"),
                             "population_type": st.get("population_type") or "healthy", "purpose": st["purpose"]}
    if c.get("route") == "iv_infusion":
        facts["infusion_time_min"] = float(st["infusion_time_min"])
    mean_n = n if form.mean_column or form.mean_row else None
    return form.model_copy(update={"constants": c, "mean_n": mean_n}), facts


def review(workbook: WorkbookGrid, form: SheetForm, recipe_id: str) -> MappingReview:
    """What a reading reads, its problems and questions (nothing saved)."""
    return review_proposal(workbook, RecipeProposal.model_validate(to_proposal(form, workbook.sheets[form.sheet])),
                           recipe_id=recipe_id)


def keep(ws: Workspace, library: DocumentLibrary, sid: str, content: dict[str, Any], checked: MappingReview, *,
         study: dict[str, Any], by: str, replace: bool = False) -> list[str]:
    """Save a checked reading: its datasets proposed (origin CLIENT, to confirm on Inputs), its dissolution records on
    the file, the recipe kept. `replace`: it replaces the earlier readings of the same sheet (their datasets rejected).
    The ids of the datasets made."""
    from modeler_project.client_data import ClientDataError, datasets_from_observations, record_mapping
    from modeler_project.dataset_register import dataset, decide_dataset, propose_dataset
    from modeler_project.datasets import DatasetError
    from modeler_project.evidence import EvidenceState

    if not checked.ready_for_confirmation or checked.recipe is None:
        raise SheetIntakeError("the reading has problems or open questions; resolve them first")
    try:
        built = datasets_from_observations(checked.concentrations, study=study, sha=content["sha256"],
                                           filename=content["file"], library=library)
        ids = [propose_dataset(ws, d, actor=by).id for d in built]
    except (ClientDataError, DatasetError, ValueError) as exc:
        raise SheetIntakeError(str(exc)) from exc
    sheets = {t.sheet for t in checked.recipe.tables}
    earlier = [m for m in content.get("mappings", []) if replace and not m.get("replaced_by")
               and any(t.get("sheet") in sheets for t in m["recipe"].get("tables", []))]
    record_mapping(ws, sid, recipe=checked.recipe.model_dump(mode="json"), dataset_ids=ids,
                   dissolution=[o.model_dump(mode="json") for o in checked.dissolution], by=by,
                   replaces=tuple(m["recipe"]["recipe_id"] for m in earlier))
    for old_id in (d for m in earlier for d in m.get("datasets", [])):
        old = dataset(ws, old_id)
        if old is not None and old.state is not EvidenceState.REJECTED:
            decide_dataset(ws, old_id, state=EvidenceState.REJECTED, by=by,
                           reason=f"replaced: {', '.join(sorted(sheets))} read again (recipe {checked.recipe.recipe_id})")
    return ids


def _read_sheets(content: dict[str, Any]) -> set[str]:
    return {t.get("sheet") for m in content.get("mappings", []) if not m.get("replaced_by")
            for t in m["recipe"].get("tables", [])}


def _points(checked: MappingReview, form: SheetForm) -> dict[str, Any] | None:
    """A draft's concentrations as a dataset's content (for the card's chart and statistics), with no study record."""
    if not checked.concentrations:
        return None
    by_series: dict[str, list[Any]] = defaultdict(list)
    for o in checked.concentrations:
        by_series[o.series].append(o)
    from modeler_project.client_data import _n_at

    series = []
    for name, group in sorted(by_series.items()):
        group = sorted(group, key=lambda o: o.time)
        sds = [o.sd for o in group]
        # every point has its SD, but a point below the LLOQ may have none: None in its place (contracts §11.7)
        spread = any(x is not None for x in sds) and all(o.sd is not None or o.below_lloq for o in group)
        series.append({"name": name, "statistic": group[0].statistic, "times": [o.time for o in group],
                       "values": [None if o.below_lloq else o.value for o in group],
                       "error": sds if spread else None, "error_kind": "SD" if spread else "none",
                       "n": next((o.n for o in group if o.n is not None), None)})
        if (n_at := _n_at([o.n for o in group])) is not None:   # n per time, as the dataset holds it (only when n varies)
            series[-1]["n_at"] = list(n_at)
    first = checked.concentrations[0]
    return {"kind": "profile", "time_unit": first.time_unit, "unit": first.unit, "study": {"lloq": form.lloq},
            "series": series, "reported": []}


def _commit_drafts(ws: Workspace, sid: str, drafts: dict[str, dict[str, Any]], *, by: str, reason: str) -> dict[str, Any]:
    from modeler_project.client_data import record_drafts

    return record_drafts(ws, sid, drafts, by=by, reason=reason)


def _problems(checked: MappingReview | None, wanted: list[str]) -> list[str]:
    """What the reading's check found, once each; a problem the card already asks about (a need) is not repeated."""
    if checked is None:
        return []
    asked = [NEED_LABEL[n].removeprefix("the ") for n in wanted if n in NEED_LABEL]
    found = dict.fromkeys([i.message for i in checked.issues] + list(checked.questions))
    return [p for p in found if not any(a in p for a in asked)]


def cleaning(grid: SheetGrid | None, form: SheetForm, checked: MappingReview | None) -> list[dict[str, Any]]:
    """What the reading left out of the sheet and what it changed, cell by cell (§3.1 step 4: "nothing silently")."""
    if grid is None:
        return []
    observations = [*(checked.concentrations if checked else ()), *(checked.dissolution if checked else ())]
    read = {o.source.cells["value"] for o in observations if "value" in o.source.cells}
    below = {o.source.cells["value"] for o in (checked.concentrations if checked else ())
             if o.below_lloq and "value" in o.source.cells}
    return [line.to_content() for line in cleaning_record(grid, form, read, below)]


def _draft(form: SheetForm, notes: list[str], checked: MappingReview | None, grid: SheetGrid | None = None) -> dict[str, Any]:
    wanted = needs(form)
    return {"form": form.model_dump(mode="json"), "notes": notes, "by": CODE, "run_id": None, "needs": wanted,
            "problems": _problems(checked, wanted), "cleaning": cleaning(grid, form, checked),
            "points": _points(checked, form) if checked and form.kind == "concentration_time" else None}


def products_of(brief: Any) -> list[dict[str, str]]:
    """The brief's products as code's reading names them (a dissolution sheet's product and role)."""
    if brief is None:
        return []
    return [{"name": str(brief.value(f"products[{i}].name") or ""), "role": str(brief.value(f"products[{i}].role") or "")}
            for i, _item in enumerate(brief.groups.get("products", ()))]


def read_on_arrival(ws: Workspace, library: DocumentLibrary, sid: str, workbook: WorkbookGrid, *, by: str, drug: str,
                    products: list[dict[str, str]], sheets: list[str] | None = None) -> dict[str, dict[str, list[str]]]:
    """Read every data sheet of the file not read yet (or the sheets named): code's reading kept as a draft, and saved
    at once when it needs nothing more. {"saved": dataset ids by sheet, "waiting": what each other sheet needs}."""
    from modeler_project.client_data import submission

    content = submission(ws, sid)
    if content is None or content.get("template"):
        return {}
    done = _read_sheets(content)
    category = {t["sheet"]: t["category"] for t in content.get("triage", [])}
    wanted = sheets if sheets is not None else [s for s, c in category.items() if c in READ and s not in done]
    drafts: dict[str, dict[str, Any]] = {}
    ready: list[tuple[str, SheetForm, MappingReview]] = []
    for sheet in wanted:
        if sheet not in workbook.sheets or category.get(sheet) not in READ:
            continue
        agent = (content.get("readings") or {}).get(sheet)
        if agent and agent.get("by") != CODE and sheets is None:
            continue                   # the reading agent's reading stands until a person reads the sheet
        form, notes = suggest(workbook.sheets[sheet], category=category[sheet], filename=content["file"], drug=drug,
                              products=products)
        checked = None
        if form.value_columns:
            try:
                checked = review(workbook, form, recipe_id=f"{sid}-draft-{sheet}")
            except ValueError:
                checked = None
        drafts[sheet] = _draft(form, notes, checked, workbook.sheets[sheet])
        if not drafts[sheet]["needs"]:
            ready.append((sheet, form, checked))
    if not drafts:
        return {"saved": {}, "waiting": {}}
    _commit_drafts(ws, sid, drafts, by=by, reason=f"read by code on arrival: {', '.join(sorted(drafts))}")
    saved: dict[str, list[str]] = {}
    for sheet, _form, _checked in ready:
        try:
            saved[sheet] = finish(ws, library, sid, sheet, {}, by=by)
        except SheetIntakeError as exc:      # a complete reading with a problem waits on its card, with the problem
            _commit_drafts(ws, sid, {sheet: {**drafts[sheet], "problems": [str(exc)]}}, by=by,
                           reason=f"{sheet}: not saved ({exc})")
    return {"saved": saved, "waiting": {s: d["needs"] for s, d in drafts.items() if s not in saved}}


ON_THE_SHEET = ("value_columns", "time_column")


def has_problem(draft: dict[str, Any]) -> bool:
    """A code reading the reading agent may do better: its check found a problem, or code could not tell which columns
    hold the values or the times. Facts the sheet does not state (the number of subjects …) are a person's to give."""
    return bool(draft.get("problems")) or any(n in ON_THE_SHEET for n in draft.get("needs", []))


def agent_could_not(ws: Workspace, sid: str, sheet: str, code: dict[str, Any], *, by: str, run_id: str, why: str) -> None:
    """Code's draft stays, saying the reading agent tried and why it could not resolve it (it is not tried again)."""
    note = f"The reading agent read this sheet too and could not resolve it: {why}. Open the sheet to read it."
    _commit_drafts(ws, sid, {sheet: {**code, "notes": [*code.get("notes", []), note], "agent_tried": run_id}},
                   by=by, reason=f"{sheet}: the reading agent could not resolve it; code's reading stays")


def adopt_agent_reading(ws: Workspace, library: DocumentLibrary, sid: str, workbook: WorkbookGrid, sheet: str,
                        form: SheetForm, notes: list[str], *, by: str, run_id: str) -> dict[str, Any]:
    """The reading agent's reading of a sheet whose code reading had a problem (plan 2026-11-05 §3.1 step 3): checked by
    code like any reading; it replaces code's draft only when its check is clean, and is then saved at once when it needs
    nothing more (its datasets to confirm on Inputs). Otherwise code's draft stays, saying the agent tried and why it
    could not resolve it. {"adopted": bool, "saved": dataset ids}."""
    from modeler_project.client_data import submission

    content = submission(ws, sid) or {}
    code = (content.get("readings") or {}).get(sheet)
    checked = None
    if form.value_columns:
        try:
            checked = review(workbook, form, recipe_id=f"{sid}-agent-{sheet}")
        except ValueError:
            checked = None
    draft = {**_draft(form, notes, checked, workbook.sheets[sheet]), "by": by, "run_id": run_id}
    if checked is None or has_problem(draft):
        if code is not None:
            agent_could_not(ws, sid, sheet, code, by=by, run_id=run_id,
                            why="; ".join(draft["problems"][:2]) or "it could not tell which columns hold the values either")
        return {"adopted": False, "saved": []}
    _commit_drafts(ws, sid, {sheet: draft}, by=by, reason=f"{sheet}: read by the reading agent (code's reading had a problem)")
    if draft["needs"]:
        return {"adopted": True, "saved": []}
    try:
        return {"adopted": True, "saved": finish(ws, library, sid, sheet, {}, by=by)}
    except SheetIntakeError as exc:          # a complete reading code will not save waits on its card, with why
        _commit_drafts(ws, sid, {sheet: {**draft, "problems": [str(exc)]}}, by=by, reason=f"{sheet}: not saved ({exc})")
        return {"adopted": True, "saved": []}


def _answer(form: SheetForm, answers: dict[str, Any]) -> SheetForm:
    """The draft with a person's answers: the study's and the product's facts (checked against their choices)."""
    constants, study = dict(form.constants), dict(form.study)
    for key, raw in answers.items():
        value = str(raw).strip() if raw is not None else ""
        if not value:
            continue
        if key == "purpose" and value not in PURPOSES:
            raise SheetIntakeError(f"what the study is for: one of {', '.join(PURPOSES)}")
        if key == "formulation" and value not in FORMULATIONS:
            raise SheetIntakeError(f"dosage form: one of {', '.join(FORMULATIONS)}")
        if key == "route" and value not in ROUTES:
            raise SheetIntakeError(f"route: one of {', '.join(ROUTES)}")
        if key == "food_state" and value not in ("fasted", "fed"):
            raise SheetIntakeError("food: fasted or fed")
        if key == "role" and value not in ROLES:
            raise SheetIntakeError(f"role: one of {', '.join(ROLES)}")
        if key in ("dose", "n", "infusion_time_min") and not _positive(value):
            raise SheetIntakeError(f"{NEED_LABEL[key]} must be a number above 0")
        if key == "n" and float(value) != int(float(value)):
            raise SheetIntakeError("the number of subjects is a whole number")
        if key in CONSTANT_ANSWERS:
            constants[key] = value
        elif key in STUDY_ANSWERS:
            study[key] = value
        else:
            raise SheetIntakeError(f"unknown answer {key!r}")
    if answers.get("dose") and not constants.get("dose_unit"):
        constants["dose_unit"] = "mg"
    return form.model_copy(update={"constants": constants, "study": study})


def finish(ws: Workspace, library: DocumentLibrary, sid: str, sheet: str, answers: dict[str, Any], *, by: str) -> list[str]:
    """Answer what a draft needs and save it when nothing is left; the dataset ids made (none: it still needs facts,
    kept on the draft). Raises SheetIntakeError with what is wrong."""
    from modeler_intake.grid import read_workbook_bytes
    from modeler_project.client_data import submission

    content = submission(ws, sid)
    if content is None:
        raise SheetIntakeError(f"no client file {sid}")
    draft = (content.get("readings") or {}).get(sheet)
    if draft is None:
        raise SheetIntakeError(f"{sheet}: no reading to finish; open the sheet to read it")
    if sheet in _read_sheets(content):
        raise SheetIntakeError(f"{sheet} is read already; open the sheet to read it again")
    form = _answer(SheetForm.model_validate(draft["form"]), answers)
    left = needs(form)
    path = ws.store.blob_path(ws.tenant_id, ws.project_id, content["sha256"])
    if path is None:
        raise SheetIntakeError("the file's bytes are not in the store")
    workbook = read_workbook_bytes(path.read_bytes(), content["file"])
    if left:
        checked = review(workbook, form, recipe_id=f"{sid}-draft-{sheet}") if form.value_columns else None
        _commit_drafts(ws, sid, {sheet: {**_draft(form, draft.get("notes", []), checked, workbook.sheets[sheet]),
                                         "by": draft.get("by", CODE), "run_id": draft.get("run_id")}},
                       by=by, reason=f"{sheet}: answered {', '.join(sorted(answers))}; still needs {', '.join(left)}")
        return []
    sent, study = _request(form)
    checked = review(workbook, sent, recipe_id=f"{sid}-r{len(content.get('mappings', [])) + 1}")
    ids = keep(ws, library, sid, content, checked, study=study, by=by)
    _commit_drafts(ws, sid, {sheet: {**draft, "form": form.model_dump(mode="json"), "needs": [], "problems": [],
                                     "cleaning": cleaning(workbook.sheets[sheet], sent, checked)}}, by=by,
                   reason=f"{sheet}: read, {len(ids)} dataset(s) to confirm")
    return ids


def drafts(ws: Workspace) -> list[dict[str, Any]]:
    """Every sheet read by code (or the agent) and not saved yet: where it waits, what it needs, its points."""
    from modeler_project.client_data import submissions

    out = []
    for content in submissions(ws):
        done = _read_sheets(content)
        category = {t["sheet"]: t["category"] for t in content.get("triage", [])}
        for sheet, draft in (content.get("readings") or {}).items():
            if sheet in done or category.get(sheet) not in READ:
                continue
            form = SheetForm.model_validate(draft["form"])
            draft = {**draft, "needs": draft["needs"] if "needs" in draft else needs(form)}   # the agent's: computed
            out.append({"sid": content["id"], "file": content["file"], "sha256": content["sha256"], "sheet": sheet,
                        "kind": "dissolution" if form.kind == "dissolution" else "concentration_time",
                        "study_id": (form.constants.get("study_id") or "").strip(), "needs": draft["needs"],
                        "problems": draft.get("problems", []), "notes": draft.get("notes", []), "by": draft.get("by", CODE),
                        "cleaning": draft.get("cleaning", []),
                        "answers": {**{k: form.constants[k] for k in CONSTANT_ANSWERS if form.constants.get(k)},
                                    **{k: form.study[k] for k in STUDY_ANSWERS if form.study.get(k)}},
                        "points": draft.get("points")})
    return out
