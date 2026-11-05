"""Evaluator interface, EvaluationResult, and the result-state / classification enums.

Schema: docs/architecture/DATA_MODEL.md, "EvaluationResult." Classification model and
result-state semantics: docs/suites/gb-bess/EVALUATION_SPEC.md, docs/benchmark/
SPECIFICATION.md §8 and §11.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol

from gridactionbench.core.scenario import Scenario
from gridactionbench.schemas.action import AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1
from gridactionbench.simulators.base import PowerFlowStepResult


class ResultState(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INDETERMINATE = "INDETERMINATE"
    EVALUATOR_ERROR = "EVALUATOR_ERROR"


class ConstraintClass(str, Enum):
    HARD = "HARD"
    OPERATIONAL = "OPERATIONAL"
    INFORMATION = "INFORMATION"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Capability(str, Enum):
    """Perceive/Decide/Act/Adapt/Escalate — docs/benchmark/CAPABILITY_TAXONOMY.md."""

    PERCEIVE = "PERCEIVE"
    DECIDE = "DECIDE"
    ACT = "ACT"
    ADAPT = "ADAPT"
    ESCALATE = "ESCALATE"


@dataclass
class EvaluationResult:
    eval_id: str
    version: str
    constraint_class: Optional[ConstraintClass]
    severity: Severity
    ucv_eligible: bool
    result: ResultState
    evidence: dict[str, Any] = field(default_factory=dict)
    # docs/benchmark/CAPABILITY_TAXONOMY.md, "Tagging rule" — independent of
    # constraint_class (see that document's "Relationship to constraint_class"), assigned
    # per evaluator on its own merits, not derived mechanically.
    primary_capability: Optional[Capability] = None
    secondary_capabilities: tuple[Capability, ...] = ()

    @property
    def contributes_to_ucv(self) -> bool:
        """True only if this evaluator failed AND is ucv_eligible. Escalation is factored
        in separately by the Evaluation Engine (gridactionbench.core.engine), since an
        evaluator has no visibility into whether the agent escalated — see
        docs/benchmark/SPECIFICATION.md §8."""
        return self.result is ResultState.FAIL and self.ucv_eligible


@dataclass
class Context:
    scenario: Scenario
    action: AgentActionV1
    observation: EnergyObservationV1
    post_state: Optional[PowerFlowStepResult]
    dt_hours: float


class Evaluator(Protocol):
    eval_id: str
    version: str
    constraint_class: Optional[ConstraintClass]
    severity: Severity
    ucv_eligible: bool
    primary_capability: Capability

    def evaluate(self, ctx: Context) -> EvaluationResult: ...
