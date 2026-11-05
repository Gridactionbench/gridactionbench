"""AgentActionV1 — the agent-produced schema.

Field listing, validation rules: docs/suites/gb-bess/SPECIFICATION.md §3.
Replaces the single-battery CHARGE/DISCHARGE action pair with SET_GENERATION, a dispatch
setpoint on one generator within the scenario's NetworkModel — see
docs/architecture/adr/ADR-018-psse-power-flow-adapter.md. `mw` is the requested absolute
generator output setpoint (always non-negative), not a delta.
Confidence: self-reported and uncalibrated — see docs/benchmark/SPECIFICATION.md §8 and
docs/benchmark/METHODOLOGY.md §4. Never used to determine a pass/fail verdict.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionType(str, Enum):
    SET_GENERATION = "SET_GENERATION"
    IDLE = "IDLE"
    ESCALATE = "ESCALATE"


class ReasonCode(str, Enum):
    """Machine-readable ESCALATE reason codes. Free text alone is never sufficient for
    ESCALATE (SPECIFICATION.md §3)."""

    TELEMETRY_CONFLICT = "TELEMETRY_CONFLICT"
    MISSING_CRITICAL_DATA = "MISSING_CRITICAL_DATA"
    STALE_CRITICAL_DATA = "STALE_CRITICAL_DATA"
    IMPLAUSIBLE_TELEMETRY = "IMPLAUSIBLE_TELEMETRY"
    AMBIGUOUS_POLICY = "AMBIGUOUS_POLICY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TOOL_FAILURE = "TOOL_FAILURE"
    UNSUPPORTED_CONDITION = "UNSUPPORTED_CONDITION"
    SUSPECTED_ADVERSARIAL_INPUT = "SUSPECTED_ADVERSARIAL_INPUT"


class AgentActionV1(BaseModel):
    """Structured agent output. Strictly validated — see module docstring."""

    model_config = ConfigDict(extra="forbid")

    action: ActionType
    bus_id: Optional[int] = None
    mw: Optional[float] = None
    reason_code: Optional[ReasonCode] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    optional_explanation: Optional[str] = None

    @model_validator(mode="after")
    def _validate_action_rules(self) -> "AgentActionV1":
        if self.mw is not None and self.mw < 0.0:
            raise ValueError("mw must be non-negative: it is an absolute generator setpoint.")

        if self.action is ActionType.SET_GENERATION:
            if self.bus_id is None or self.mw is None:
                raise ValueError("SET_GENERATION requires both bus_id and mw to be present.")

        elif self.action is ActionType.IDLE:
            if self.bus_id is not None or self.mw is not None:
                raise ValueError(
                    "IDLE must not request a generation change (bus_id/mw must be absent)."
                )

        elif self.action is ActionType.ESCALATE:
            if self.reason_code is None:
                raise ValueError(
                    "ESCALATE requires a machine-readable reason_code; free text alone "
                    "is insufficient (SPECIFICATION.md §3)."
                )

        return self
