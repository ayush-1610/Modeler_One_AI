"""Analysis templates: the versioned recipe of each PBPK application (DDI, VBE …) a question of interest pins.

A template names what the application needs (a validated model, data items), the inputs a person gives, the steps
that run, the technical criteria and the report sections. It is scientific content, governed like the rulesets: DRAFT
until a PBPK SME and QA sign it, and locked (CLAUDE.md). An input marked ``never_default`` is the person's to give
(e.g. VBE's intra-subject variability and trial size, D-26): the schema refuses a default for it, and `check_inputs`
names it until it is given.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

InputKind = Literal["formulation", "variability", "integer", "number", "fraction", "limits", "text"]


class TemplateInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    kind: InputKind
    required: bool = True
    default: Any = None
    unit: str | None = None
    note: str = ""
    never_default: bool = False

    @model_validator(mode="after")
    def _no_default_when_never(self) -> TemplateInput:
        if self.never_default and self.default is not None:
            raise ValueError(f"input {self.id!r} is never defaulted, yet the template gives it one")
        return self


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lower: float = Field(gt=0)
    upper: float = Field(gt=0)
    ci_level: float = Field(gt=0, lt=1)
    verified: bool
    source: str


class TemplateStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    uses: str
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")


class AnalysisTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: str
    applies_to: tuple[str, ...]
    status: Literal["DRAFT", "APPROVED"]
    requires: dict[str, Any] = Field(default_factory=dict)
    inputs: tuple[TemplateInput, ...] = ()
    limits: dict[str, Limits] = Field(default_factory=dict)
    steps: tuple[TemplateStep, ...] = ()
    default_technical_criteria: tuple[dict[str, Any], ...] = ()
    report_sections: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _limits_named(self) -> AnalysisTemplate:
        for i in self.inputs:
            if i.kind == "limits" and i.default is not None and i.default not in self.limits:
                raise ValueError(f"input {i.id!r} defaults to limits {i.default!r}, which the template does not define")
        return self

    def input(self, input_id: str) -> TemplateInput:
        return next(i for i in self.inputs if i.id == input_id)


def _files() -> list[str]:
    return sorted(f.name for f in resources.files(__name__).iterdir() if f.name.endswith(".yaml"))


@lru_cache
def load_template(template_id: str) -> AnalysisTemplate:
    """The template with this id; raises KeyError for an unknown one."""
    for name in _files():
        doc = yaml.safe_load(resources.files(__name__).joinpath(name).read_text(encoding="utf-8"))
        if doc.get("id") == template_id:
            return AnalysisTemplate.model_validate(doc)
    raise KeyError(f"no analysis template {template_id!r}")


def list_templates() -> tuple[AnalysisTemplate, ...]:
    return tuple(load_template(yaml.safe_load(resources.files(__name__).joinpath(n).read_text(encoding="utf-8"))["id"])
                 for n in _files())


def _problem(spec: TemplateInput, value: Any, template: AnalysisTemplate) -> str | None:
    """Why `value` is not a valid `spec` input, or None."""
    if spec.kind in ("integer", "number", "fraction"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{spec.label}: a number is needed"
        if spec.kind == "integer" and (not float(value).is_integer() or value < 1):
            return f"{spec.label}: a whole number of at least 1 is needed"
        if spec.kind == "fraction" and not 0 < value <= 1:
            return f"{spec.label}: a fraction in (0, 1] is needed"
        if spec.kind == "number" and value <= 0:
            return f"{spec.label}: a number above 0 is needed"
    elif spec.kind == "variability":
        rows = value if isinstance(value, list) else []
        if not rows:
            return f"{spec.label}: at least one parameter with its CV and source is needed"
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("parameter", "")).strip():
                return f"{spec.label}: each entry names its parameter"
            cv = row.get("cv_percent")
            if isinstance(cv, bool) or not isinstance(cv, int | float) or cv <= 0:
                return f"{spec.label}: {row.get('parameter')}: a CV above 0 % is needed"
            if not str(row.get("source", "")).strip():
                return f"{spec.label}: {row.get('parameter')}: its source is needed (never an invented number)"
    elif spec.kind == "limits":
        if value not in template.limits:
            return f"{spec.label}: one of {', '.join(template.limits)}"
    elif not str(value).strip():
        return f"{spec.label}: a value is needed"
    return None


def check_inputs(template: AnalysisTemplate, values: dict[str, Any]) -> list[str]:
    """What is missing or wrong in a person's inputs for `template`: one readable line each (empty when complete).
    A ``never_default`` input missing is named, never filled in."""
    problems = []
    for spec in template.inputs:
        value = values.get(spec.id, spec.default)
        if value is None:
            if spec.required:
                problems.append(f"{spec.label}: not given" + (" (required; never defaulted)" if spec.never_default else ""))
            continue
        if (why := _problem(spec, value, template)) is not None:
            problems.append(why)
    unknown = sorted(set(values) - {i.id for i in template.inputs})
    if unknown:
        problems.append(f"unknown inputs: {', '.join(unknown)}")
    return problems


def resolved_limits(template: AnalysisTemplate, values: dict[str, Any]) -> Limits:
    """The limits the inputs choose (the template's default when none is chosen)."""
    spec = next(i for i in template.inputs if i.kind == "limits")
    return template.limits[values.get(spec.id, spec.default)]
