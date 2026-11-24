"""What the Data room holds and shows (plan 2026-11-21 v2 §5-§8): every value with its source and status.

Frozen pydantic, like the rest of the domain. Nothing here computes; `extract`, `clinical`, `invitro` and `assemble`
fill these from the agents' descriptions and the delivery's cells.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_intake.room_specs import Fact, FileTriage, QuestionCard, TableDescription

Status = Literal["verified", "sponsor", "literature", "calculated", "entered", "conflict", "missing"]
Severity = Literal["error", "warning", "info"]
Role = Literal["development", "calibration", "verification", "prediction"]


class _B(BaseModel):
    # every field is in every answer (the API serves these as they are), so the contract marks each one required
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class Chip(_B):
    """Where a value was read: a file, a part (p3, sheet:Name, body), a line and a cell of it."""

    file: str
    sha256: str = ""
    part: str
    line: int
    cell: int | None = None          # 1-based cell of the line; None: the whole line (a quote)
    text: str = ""                   # the cell's or the quote's text as written
    box: tuple[float, float, float, float] | None = None   # a page cell: points, top-left origin
    ref: str = ""                    # a sheet cell's A1 address; a Word table cell


class Problem(_B):
    code: str                        # e.g. QUOTE_NOT_FOUND, ROW_SHORT, MEAN_ROW_DIFFERS
    message: str                     # one plain sentence
    severity: Severity = "warning"
    where: Chip | None = None


class Value(_B):
    """One input or finding, as the report shows it: value, unit, source(s), status."""

    key: str                         # e.g. substance.mw, study.17-06-138.n_completed
    label: str
    value: float | str | None = None
    unit: str = ""
    as_written: str = ""
    status: Status = "sponsor"
    sources: tuple[Chip, ...] = ()
    rule: str = ""                   # a calculated value: how
    note: str = ""
    others: tuple[Value, ...] = ()   # a conflict: the other sources' values


# --- read from the delivery --------------------------------------------------------------------------------------------


class ReadCell(_B):
    role: str
    text: str
    chip: Chip
    label: str = ""
    unit: str = ""
    time: float | None = None
    group: str = ""


class ReadRow(_B):
    line: int
    cells: tuple[ReadCell, ...]
    summary: str = ""                # "mean", "rsd" …: the client's own summary line


class ReadTable(_B):
    id: str                          # stable: file sha · part · first line
    description: TableDescription
    sha256: str = ""
    rows: tuple[ReadRow, ...] = ()
    problems: tuple[Problem, ...] = ()
    decimal_comma: bool = False      # its numbers use a decimal comma ("0,058"): `extract.uses_decimal_comma`


class CheckedFact(_B):
    fact: Fact
    ok: bool
    chip: Chip | None = None
    number: float | None = None      # the value as a number, when it is one
    problem: str = ""


# --- clinical ----------------------------------------------------------------------------------------------------------


class Sample(_B):
    subject: str
    period: str = ""
    treatment: str = ""
    sequence: str = ""
    time_h: float
    text: str
    value: float | None              # None: missing or below the LLOQ (see blq)
    actual_h: float | None = None    # the actual sampling time, when the line gives one (kept for Tmax beside the client's)
    blq: bool = False
    missing: bool = False
    chip: Chip | None = None


class Arm(_B):
    treatment: str                   # the code as the data writes it (A, B, R, T …)
    meaning: str = ""                # as the client defines it ("reference product")
    product: str = ""                # the question card's product
    role: str = ""                   # reference / test / original / reformulated
    source: Chip | None = None
    tied: str = ""                   # how code tied it to its product when no document names it (said on the page)


class MeanPoint(_B):
    time_h: float
    n: int                           # values in the arithmetic mean (below the LLOQ counted as 0)
    mean: float | None
    sd: float | None
    n_geo: int                       # quantifiable values in the geometric mean
    geomean: float | None
    n_blq: int = 0
    n_missing: int = 0


class ArmProfile(_B):
    treatment: str
    analysis_set: str
    n_subjects: int
    points: tuple[MeanPoint, ...]


class SubjectNca(_B):
    subject: str
    period: str
    treatment: str
    cmax: float | None = None
    tmax: float | None = None
    tmax_actual: float | None = None  # the actual time of our Cmax sample, when the data gives actual times
    auc_t: float | None = None        # linear-up/log-down (ours)
    auc_t_linear: float | None = None  # linear trapezoidal (as most CROs compute it)
    auc_inf: float | None = None
    t_half: float | None = None
    lambda_z: float | None = None
    client: dict[str, float] = Field(default_factory=dict)       # the client's values for this profile, by role
    differences: dict[str, float] = Field(default_factory=dict)  # percent (tmax: hours), ours − the client's


class SubjectSet(_B):
    name: str                        # dosed, completed, evaluable, modeling, auc, client_statistical
    label: str
    subjects: tuple[str, ...]
    rule: str
    source: Status = "calculated"
    sources: tuple[Chip, ...] = ()


class Exposure(_B):
    treatment: str
    analysis_set: str
    n: int
    metric: str                      # cmax, auc_t, auc_inf, tmax
    statistic: str                   # geometric_mean, arithmetic_mean, median
    value: float | None
    unit: str = ""
    client: float | None = None
    difference_percent: float | None = None


class RoomStudy(_B):
    """One clinical study as the room shows it (named apart from the API's other study views)."""

    study_id: str
    facts: tuple[Value, ...] = ()
    arms: tuple[Arm, ...] = ()
    periods: tuple[str, ...] = ()
    times_h: tuple[float, ...] = ()
    sets: tuple[SubjectSet, ...] = ()
    excluded: dict[str, str] = Field(default_factory=dict)       # subject -> why (out of the modeling set)
    profiles: tuple[ArmProfile, ...] = ()
    nca: tuple[SubjectNca, ...] = ()
    exposures: tuple[Exposure, ...] = ()
    nca_method_client: str = ""      # the trapezoid rule the client's values follow, as found
    concentration_unit: str = ""
    lloq: float | None = None
    problems: tuple[Problem, ...] = ()


# --- in vitro ---------------------------------------------------------------------------------------------------------


class DissolutionView(_B):
    id: str
    product: str = ""
    batch: str = ""
    medium: str = ""
    ph: float | None = None
    apparatus: str = ""
    rpm: float | None = None
    volume_ml: float | None = None
    n_units: int = 0
    times_min: tuple[float, ...] = ()
    mean: tuple[float, ...] = ()
    sd: tuple[float | None, ...] = ()
    client_mean: tuple[float | None, ...] = ()
    weibull: dict[str, float | str | bool | None] = Field(default_factory=dict)
    weibull_curve: tuple[tuple[float, float], ...] = ()   # the fitted curve: (min, % dissolved), drawn beside the means
    very_rapid: bool = False         # ≥ 85 % within 15 min
    plateau: bool = False
    sources: tuple[Chip, ...] = ()
    problems: tuple[Problem, ...] = ()


class F2View(_B):
    test: str                        # DissolutionView ids
    reference: str
    value: float | None
    similar: bool | None
    applicable: bool
    reasons: tuple[str, ...] = ()


class CompositionRow(_B):
    component: str
    function: str = ""
    amounts: dict[str, str] = Field(default_factory=dict)   # product -> amount as written (mg/unit or %)
    changed: bool = False
    sources: tuple[Chip, ...] = ()


class SolubilityRow(_B):
    medium: str
    ph: float | None = None
    solubility_mg_ml: float | None = None
    as_written: str = ""
    volume_for_dose_ml: float | None = None
    fraction_in_glass: float | None = None
    fraction_in_medium: float | None = None
    sources: tuple[Chip, ...] = ()


# --- what the modeler settles ---------------------------------------------------------------------------------------------


class Option(_B):
    id: str
    label: str
    detail: str = ""


class RoomDecision(_B):
    """A modeling choice waiting for the modeler (named apart from the API's other decisions)."""

    id: str                          # stable: e.g. analysis-set:17-06-138
    title: str
    question: str
    options: tuple[Option, ...]
    suggested: str                   # an option id
    why: str = ""
    evidence: tuple[Chip, ...] = ()
    chosen: str | None = None
    reason: str = ""
    by: str = ""
    at: str = ""


class DataRequest(_B):
    id: str                          # A-01 … D-12
    area: Literal["A", "B", "C", "D"]
    title: str
    why: str
    wording: str = ""
    status: Literal["open", "not_needed", "answered"] = "open"
    checklist: str = ""
    input: str = ""                  # the PK-Sim input it would fill (an InputRow name), when a person may enter it


class PlanRow(_B):
    formulation: str
    condition: str
    observed: str
    role: Role
    why: str = ""


class InputRow(_B):
    """One PK-Sim input: the building block, the PK-Sim (or CPF) name, the value, its source and status."""

    block: Literal["compound", "formulation", "individual", "protocol", "event", "observed", "target"]
    owner: str = ""                  # the formulation, study or arm it belongs to
    name: str                        # PK-Sim name (harvested) or CPF id
    label: str
    value: float | str | None = None
    unit: str = ""
    status: Status = "missing"
    sources: tuple[Chip, ...] = ()
    decision: str = ""               # the decision it follows, when it depends on one
    note: str = ""


class FileView(_B):
    path: str
    name: str
    sha256: str
    kind: str
    pages: int = 0
    ocr_pages: tuple[int, ...] = ()
    turned_pages: tuple[int, ...] = ()
    state: str = "read"
    reason: str = ""
    duplicate_of: str | None = None
    same_content_as: str | None = None
    triage: FileTriage | None = None


class Section(_B):
    id: str
    title: str
    finding: str = ""
    status: Literal["ok", "attention", "missing", "empty"] = "empty"
    computed: str = ""      # code's own finding; the writer's line replaces it only while it was written against this one


class MadeBy(_B):
    """Who wrote one stage's answer for one file (or, `file` empty, for the delivery): the evidence report's "How this
    report was made" (the governance review, 2026-11-22). `service`: where the model ran ("our server", or the cloud
    service the file was sent to); `switches`: each model that could not answer before it, and why."""

    stage: str
    file: str = ""
    model: str
    service: str
    prompt: str = ""
    at: str = ""
    note: str = ""
    switches: tuple[str, ...] = ()


class DataRoomView(_B):
    """The Data room of one project, as the page and the report show it."""

    rules: str
    files: tuple[FileView, ...] = ()
    question: QuestionCard | None = None
    question_confirmed: bool = False
    sections: tuple[Section, ...] = ()
    substance: tuple[Value, ...] = ()
    adme: tuple[Value, ...] = ()
    products: tuple[Value, ...] = ()
    composition: tuple[CompositionRow, ...] = ()
    solubility: tuple[SolubilityRow, ...] = ()
    dissolution: tuple[DissolutionView, ...] = ()
    f2: tuple[F2View, ...] = ()
    studies: tuple[RoomStudy, ...] = ()
    decisions: tuple[RoomDecision, ...] = ()
    requests: tuple[DataRequest, ...] = ()
    plan: tuple[PlanRow, ...] = ()
    inputs: tuple[InputRow, ...] = ()
    problems: tuple[Problem, ...] = ()
    made_by: tuple[MadeBy, ...] = ()
    made_summary: str = ""


Value.model_rebuild()
