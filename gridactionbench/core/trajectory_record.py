"""TrajectoryRecord — a formal, versioned container for a Trial's ordered DecisionRecords.

See docs/benchmark/TASK_MODEL.md, "Trajectory records" (docs/project/GAP_ANALYSIS.md P1
item 4). `DecisionRecord` (docs/benchmark/SPECIFICATION.md §7) remains the atomic unit of
evidence — this module does not replace it, only formalises the grouping that
`EpisodeResult` (gridactionbench/core/episode.py) already carries informally: run_id, task
family, instance_id, seed, agent/model metadata, initial-world-state hash, the ordered
DecisionRecords themselves, termination reason, terminal state, and aggregate
reliability/effectiveness metrics.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from gridactionbench.agents.base import AgentAdapter
from gridactionbench.core.decision_record import DecisionRecord
from gridactionbench.core.episode import EpisodeResult, EpisodeSpec
from gridactionbench.core.scenario import TaskFamilyTags
from gridactionbench.provenance.capture import capture_git_commit, capture_runtime_version

TRAJECTORY_RECORD_VERSION = "0.1.0"


def _hash_world_state(state: dict[str, Any]) -> str:
    """A stable hash of the initial world state — sorted-key JSON so field ordering never
    changes the hash, only the actual values do."""
    canonical = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TrajectoryRecord(BaseModel):
    """One Trial's complete trajectory (docs/benchmark/TASK_MODEL.md ontology). Today built
    only for Operational trials (`build_trajectory_record_from_episode`, below) — the
    ontology's "For an Atomic trial: one DecisionRecord" case is already served directly by
    `DecisionRecord` and does not require wrapping in a single-element `TrajectoryRecord`
    unless a future caller specifically needs one."""

    model_config = ConfigDict(extra="forbid")

    trajectory_record_version: str = TRAJECTORY_RECORD_VERSION
    run_id: str
    task_mode: str  # "Atomic" | "Sequential" | "Operational" — docs/benchmark/TASK_MODEL.md
    # GB-BESS v0.1's EpisodeSpecs are not yet separately parameterised beyond their fixed
    # episode_id (unlike a ScenarioTemplate, which produces many instances) — task_family
    # and instance_id are therefore identical today. They are kept as distinct fields, not
    # collapsed into one, because a future parameterised Operational Task Family (multiple
    # instances of "GB-BESS-EP-003"-shaped episodes with different numeric ranges) would
    # need them to diverge without a schema change.
    task_family: str
    instance_id: str
    agent_id: str
    agent_version: str
    agent_type: str
    random_seed: Optional[int] = None
    initial_state_hash: str
    steps: list[DecisionRecord]
    # run_episode() (gridactionbench/core/episode.py) has no early-termination path today —
    # an invalid/errored step's world state simply does not advance, but the loop still
    # runs every declared step — so "steps_exhausted" is the only value this field takes
    # currently. Kept as a string, not a fixed-membership enum, for whatever a future
    # early-terminating trial (Sequential or otherwise) needs to record.
    termination_reason: str
    terminal_state: dict[str, Any]
    any_ucv: bool
    ucv_count: int
    # Effectiveness half of the reliability/effectiveness split (docs/benchmark/
    # RELIABILITY_BOUNDARY_MODEL.md) — mean(achieved/best_case) over this trajectory's own
    # steps only, same exclusion discipline as Report.economic_decision_quality
    # (gridactionbench/reporting/report.py): a step with no economic incentive at all is
    # excluded, not scored as 0% or 100%.
    mean_economic_decision_quality: Optional[float] = None
    task_family_tags: Optional[TaskFamilyTags] = None
    git_commit: Optional[str] = None
    runtime_version: str
    timestamp: datetime


def build_trajectory_record_from_episode(
    episode: EpisodeSpec,
    result: EpisodeResult,
    agent: AgentAdapter,
    run_id: str | None = None,
    random_seed: int | None = None,
) -> TrajectoryRecord:
    """Wraps an already-computed EpisodeResult (gridactionbench/core/episode.py::
    run_episode()) into a TrajectoryRecord — purely additive, does not change run_episode()
    or any check_*() failure-signature function. Pass the same `run_id` given to
    run_episode() so the two stay consistent (both default to `episode.episode_id`)."""
    run_id = run_id or episode.episode_id
    steps = result.step_records
    initial_state_hash = _hash_world_state(steps[0].simulator_pre_state)

    eq_n = 0
    eq_sum = 0.0
    for step in steps:
        best_case = step.objective_value_best_case_gbp
        achieved = step.objective_value_achieved_gbp
        if best_case is not None and best_case > 0 and achieved is not None:
            eq_n += 1
            eq_sum += max(0.0, min(1.0, achieved / best_case))
    mean_eq = (eq_sum / eq_n) if eq_n else None

    return TrajectoryRecord(
        run_id=run_id,
        task_mode=episode.task_mode,
        task_family=episode.episode_id,
        instance_id=episode.episode_id,
        agent_id=agent.agent_id,
        agent_version=agent.agent_version,
        agent_type=agent.agent_type,
        random_seed=random_seed,
        initial_state_hash=initial_state_hash,
        steps=steps,
        termination_reason="steps_exhausted",
        terminal_state={"world_mw_after_step": result.world_mw_after_step[-1] if result.world_mw_after_step else None},
        any_ucv=result.any_ucv,
        ucv_count=result.ucv_count,
        mean_economic_decision_quality=mean_eq,
        task_family_tags=steps[0].task_family_tags,
        git_commit=capture_git_commit(),
        runtime_version=capture_runtime_version(),
        timestamp=datetime.now(timezone.utc),
    )


class TrajectoryJsonlWriter:
    """Append-only JSONL writer for TrajectoryRecords — mirrors
    gridactionbench.core.decision_record.JsonlWriter exactly, for the same reasons."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: TrajectoryRecord) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json())
            f.write("\n")

    def read_all(self) -> list[TrajectoryRecord]:
        if not self.path.exists():
            return []
        records = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(TrajectoryRecord(**json.loads(line)))
        return records
