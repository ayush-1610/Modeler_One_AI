"""ICH M15 (Step 4, adopted 29 Jan 2026) assessment table: structure and completeness rules.

Item names and stage rules follow Appendix 1 of the guideline. The platform checks completeness
and consistency; people assign every rating.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from pbpk_domain.issues import Issue


class Rating(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_SCALE = (Rating.LOW, Rating.MEDIUM, Rating.HIGH)


class Stage(StrEnum):
    PLANNING = "planning"
    SUBMISSION = "submission"


def allowed_model_risk(influence: Rating, consequence: Rating) -> tuple[Rating, ...]:
    """Model-risk ratings consistent with M15 §2.1.5.

    Equal inputs give that rating. When they differ, model risk "may be driven by the most
    influential of the two", so any rating between them is admissible, and the choice has to be
    justified.
    """
    lo, hi = sorted((_SCALE.index(influence), _SCALE.index(consequence)))
    return _SCALE[lo : hi + 1]


class RatedElement(BaseModel):
    description: str = ""
    rating: Rating | None = None
    justification: str = ""


class AssessmentTable(BaseModel):
    """One table per question of interest (M15 Appendix 1, footnote 1)."""

    question_of_interest: str = ""
    context_of_use: str = ""
    model_influence: RatedElement = Field(default_factory=RatedElement)
    consequence_of_wrong_decision: RatedElement = Field(default_factory=RatedElement)
    model_risk: RatedElement = Field(default_factory=RatedElement)
    model_impact: RatedElement = Field(default_factory=RatedElement)
    # MIDD planning stage (also required at submission, Appendix 1 footnote 3)
    technical_criteria: str = ""
    appropriateness_of_proposed_midd: str = ""
    # MIDD evidence submission stage
    evaluation_of_models_and_outcomes: str = ""
    outcome_of_midd_evidence_assessment: str = ""


_RATED = ("model_influence", "consequence_of_wrong_decision", "model_risk", "model_impact")


def validate_table(table: AssessmentTable, stage: Stage) -> list[Issue]:
    issues: list[Issue] = []

    def require(field: str) -> None:
        if not getattr(table, field).strip():
            issues.append(Issue("MISSING_ENTRY", field, "entry is required at this stage"))

    require("question_of_interest")
    require("context_of_use")

    for field in _RATED:
        element: RatedElement = getattr(table, field)
        if not element.description.strip():
            issues.append(Issue("MISSING_DESCRIPTION", field, "describe the element before rating it"))
        if element.rating is None:
            issues.append(Issue("MISSING_RATING", field, "rate as low, medium, or high"))
        if not element.justification.strip():
            issues.append(Issue("MISSING_JUSTIFICATION", field, "M15 expects a justification for every rating"))

    influence, consequence, risk = (
        table.model_influence.rating,
        table.consequence_of_wrong_decision.rating,
        table.model_risk.rating,
    )
    if influence and consequence and risk:
        allowed = allowed_model_risk(influence, consequence)
        if risk not in allowed:
            issues.append(
                Issue(
                    "MODEL_RISK_INCONSISTENT",
                    "model_risk",
                    f"with influence={influence} and consequence={consequence}, model risk must be one of "
                    f"{', '.join(allowed)} (got {risk})",
                )
            )

    require("technical_criteria")
    require("appropriateness_of_proposed_midd")
    if stage is Stage.SUBMISSION:
        require("evaluation_of_models_and_outcomes")
        require("outcome_of_midd_evidence_assessment")

    return issues
