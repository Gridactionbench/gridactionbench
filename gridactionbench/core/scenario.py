"""Scenario, Oracle, and scenario-file loading.

Schema: docs/architecture/DATA_MODEL.md, "Scenario file." Oracle/Observation separation:
docs/architecture/adr/ADR-005-oracle-observation-separation.md — the Oracle is ground
truth, visible to the Evaluation Engine; the Observation (derived from the Oracle plus
this scenario's `observation_overrides`) is what the Agent actually sees.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field
from gridactionbench import FRAMEWORK_VERSION

from gridactionbench.schemas.observation import (
    EnergyObservationV1,
    MarketState,
    NetworkModel,
    OperationalPolicy,
    Telemetry,
)


class InformationRequirement(BaseModel):
    """Scenario-defined information contract for one observation field.

    Never a global benchmark constant — docs/suites/gb-bess/SPECIFICATION.md §8.
    """

    model_config = ConfigDict(extra="forbid")

    required_for: list[str] = Field(default_factory=list)
    max_age_seconds: Optional[int] = None
    conflict_tolerance: Optional[float] = None
    plausible_upper_bound_mva: Optional[float] = None
    valid_sources: Optional[list[str]] = None


class EscalationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    permitted: bool = True


class TaskFamilyTags(BaseModel):
    """Stress-dimension (`docs/benchmark/STRESS_DIMENSIONS.md`) and capability
    (`docs/benchmark/CAPABILITY_TAXONOMY.md`) metadata inherited from the
    `ScenarioTemplate`/`EpisodeSpec` that produced this scenario — declared by whoever
    designs the Task Family, never measured from results (STRESS_DIMENSIONS.md, "How
    C/U/H metadata should be used once tagged"). `Scenario.task_family_tags` is `None` for
    scenarios not produced by a tagged Task Family — the 20 hand-authored v0.1 scenarios
    predate this scheme and are not retroactively tagged (`docs/project/GAP_ANALYSIS.md`
    scoped this to `ScenarioTemplate`/`EpisodeSpec` specifically, not every scenario)."""

    model_config = ConfigDict(extra="forbid")

    task_mode: str  # "Atomic" | "Sequential" | "Operational" — docs/benchmark/TASK_MODEL.md
    primary_capability: str
    complexity_rung: str
    u_classes: tuple[str, ...]
    autonomy_burden: str


class Oracle(BaseModel):
    """Full ground truth for a scenario. Visible to the Evaluation Engine, not the Agent."""

    model_config = ConfigDict(extra="forbid")

    network_model: NetworkModel
    market: MarketState = Field(default_factory=MarketState)
    operational_policy: OperationalPolicy = Field(default_factory=OperationalPolicy)


class Scenario(BaseModel):
    """A single GB-BESS scenario instance. See docs/architecture/DATA_MODEL.md."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    scenario_version: str
    suite: str = "gb-bess"
    suite_version: str = "0.1.0"
    family: str
    source_type: str = "synthetic"

    oracle: Oracle
    # Fields where the Agent's Observation differs from the Oracle — DATA-family scenarios
    # use this to model missing/stale/conflicting/implausible data. Keys are dotted paths
    # resolved against the derived observation (e.g. "network_model.branches.0.mva_flow",
    # "telemetry.field_status.voltage").
    observation_overrides: dict[str, Any] = Field(default_factory=dict)

    information_requirements: dict[str, InformationRequirement] = Field(default_factory=dict)
    escalation: EscalationSpec = Field(default_factory=EscalationSpec)

    permitted_actions: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    # Named in docs/benchmark/SPECIFICATION.md §4 / docs/architecture/DATA_MODEL.md since
    # Phase 0 ("invalid / valid / valid-but-suboptimal / preferred / ...") but never
    # implemented until 2026-09-09, when MKT-PREFERRED-ACTION-001
    # (gridactionbench/evaluators/gb_bess/mkt.py) became its first consumer. Empty (the
    # default) means no preference declared — never a silently-assumed default, same
    # discipline as information_requirements.
    preferred_actions: list[str] = Field(default_factory=list)

    review_status: str = "DRAFT"

    # See TaskFamilyTags above. Populated post-hoc by generate() (gridactionbench/
    # scenarios/generator.py) and run_episode() (gridactionbench/core/episode.py) —
    # never by a ScenarioTemplate's build function or an EpisodeSpec's build_step
    # function directly, so neither needed to change (docs/project/GAP_ANALYSIS.md).
    task_family_tags: Optional[TaskFamilyTags] = None

    def build_observation(self) -> EnergyObservationV1:
        """Derive the Agent-visible Observation from this scenario's Oracle.

        Per docs/architecture/adr/ADR-005: the Observation is never mechanically derived
        by a generic "hide some fields" rule — DATA-family scenarios need the freedom to
        make the Observation actively wrong, not merely incomplete. `observation_overrides`
        is this scenario's explicit declaration of exactly how (identity by default).
        """
        base = {
            "benchmark_version": FRAMEWORK_VERSION,
            "suite_version": self.suite_version,
            "scenario_id": self.scenario_id,
            "timestamp": datetime.now(timezone.utc),
            "network_model": self.oracle.network_model.model_dump(),
            "market": self.oracle.market.model_dump(),
            "telemetry": Telemetry().model_dump(),
            "operational_policy": self.oracle.operational_policy.model_dump(),
        }
        for dotted_path, value in self.observation_overrides.items():
            _set_dotted(base, dotted_path, value)
        return EnergyObservationV1(**base)


def _set_dotted(d: dict[str, Any], dotted_path: str, value: Any) -> None:
    """A numeric path segment indexes into a list (e.g. "network_model.branches.0.mva_flow"
    for this benchmark's post-pivot list-shaped NetworkModel fields); every other segment
    indexes into a dict, creating it if absent."""
    parts = dotted_path.split(".")
    cursor: Any = d
    for part in parts[:-1]:
        key: Any = int(part) if part.isdigit() else part
        if isinstance(cursor, list):
            cursor = cursor[key]
        else:
            cursor = cursor.setdefault(key, {})
    last: Any = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
    cursor[last] = value


def load_scenario(path: Path | str) -> Scenario:
    """Load and validate a single scenario YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Scenario(**raw)


def load_scenario_dir(directory: Path | str) -> list[Scenario]:
    """Load every scenario YAML file in a directory, sorted by scenario_id."""
    directory = Path(directory)
    scenarios = [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]
    return sorted(scenarios, key=lambda s: s.scenario_id)
