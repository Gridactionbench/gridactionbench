"""Tests for TrajectoryRecord (gridactionbench/core/trajectory_record.py).

See docs/benchmark/TASK_MODEL.md, "Trajectory records" — added September 2026 strategic
realignment, closing docs/project/GAP_ANALYSIS.md's P1 item 4. This is a formal,
versioned, additive schema wrapping the ordered DecisionRecords EpisodeResult already
produces — it does not change run_episode() or any check_*() failure-signature function.
"""

from __future__ import annotations

from baselines.always_escalate.agent import AlwaysEscalateAgent
from baselines.rule_based.agent import RuleBasedAgent
from baselines.seeded_failures.ignore_thermal_limit import IgnoreThermalLimitAgent
from gridactionbench.core.episode import run_episode
from gridactionbench.core.trajectory_record import (
    TrajectoryJsonlWriter,
    TrajectoryRecord,
    build_trajectory_record_from_episode,
)
from gridactionbench.scenarios.gb_bess.episodes import EPISODES

DT_HOURS = 0.5


def _build(episode_id: str, agent) -> TrajectoryRecord:
    episode, _check_fn = EPISODES[episode_id]
    result = run_episode(episode, agent, DT_HOURS)
    return build_trajectory_record_from_episode(episode, result, agent)


def test_trajectory_record_wraps_every_step_of_the_episode():
    episode, _check_fn = EPISODES["GB-BESS-EP-003"]
    trajectory = _build("GB-BESS-EP-003", RuleBasedAgent(dt_hours=DT_HOURS))
    assert len(trajectory.steps) == episode.steps
    assert trajectory.task_family == "GB-BESS-EP-003"
    assert trajectory.instance_id == "GB-BESS-EP-003"
    assert trajectory.task_mode == "Operational"


def test_trajectory_record_reflects_the_sequential_reclassification():
    """GB-BESS-EP-001/EP-002 were reclassified task_mode="Sequential" 2026-09-09
    (docs/benchmark/TASK_MODEL.md) — a TrajectoryRecord built from either must reflect
    that, not the "Operational" every episode used to carry unconditionally."""
    trajectory = _build("GB-BESS-EP-001", RuleBasedAgent(dt_hours=DT_HOURS))
    assert trajectory.task_mode == "Sequential"
    assert trajectory.task_family_tags.task_mode == "Sequential"


def test_trajectory_record_carries_the_episode_s_task_family_tags():
    trajectory = _build("GB-BESS-EP-003", RuleBasedAgent(dt_hours=DT_HOURS))
    episode, _check_fn = EPISODES["GB-BESS-EP-003"]
    assert trajectory.task_family_tags is not None
    assert trajectory.task_family_tags.primary_capability == episode.primary_capability.value


def test_trajectory_record_ucv_aggregates_match_episode_result():
    trajectory = _build("GB-BESS-EP-002", IgnoreThermalLimitAgent(dt_hours=DT_HOURS))
    episode, _check_fn = EPISODES["GB-BESS-EP-002"]
    result = run_episode(episode, IgnoreThermalLimitAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert trajectory.any_ucv == result.any_ucv
    assert trajectory.ucv_count == result.ucv_count


def test_initial_state_hash_is_deterministic_given_the_same_episode_and_agent():
    a = _build("GB-BESS-EP-001", RuleBasedAgent(dt_hours=DT_HOURS))
    b = _build("GB-BESS-EP-001", RuleBasedAgent(dt_hours=DT_HOURS))
    assert a.initial_state_hash == b.initial_state_hash


def test_initial_state_hash_differs_for_a_different_episode():
    a = _build("GB-BESS-EP-001", RuleBasedAgent(dt_hours=DT_HOURS))
    b = _build("GB-BESS-EP-002", RuleBasedAgent(dt_hours=DT_HOURS))
    assert a.initial_state_hash != b.initial_state_hash


def test_mean_economic_decision_quality_reflects_unnecessary_escalation():
    """AlwaysEscalateAgent escalates on every GB-BESS-EP-006 step, including the odd
    (fully-specified, no escalation needed) ones that do carry a real economic incentive
    (reference_price_gbp_mwh=40.0) — escalating there achieves 0.0 of that best-case value,
    so mean_economic_decision_quality is 0.0, not None. This is the same "reliable but not
    fully effective" pattern docs/benchmark/SCORING.md's AlwaysEscalateAgent calibration
    result already documents at single-step scale."""
    trajectory = _build("GB-BESS-EP-006", AlwaysEscalateAgent())
    assert trajectory.mean_economic_decision_quality == 0.0


def test_termination_reason_is_steps_exhausted_for_every_episode_today():
    """run_episode() has no early-termination path yet (gridactionbench/core/episode.py) —
    pinning this so a future early-terminating trial is a deliberate change, not a silent
    drift in what this field means."""
    trajectory = _build("GB-BESS-EP-004", RuleBasedAgent(dt_hours=DT_HOURS))
    assert trajectory.termination_reason == "steps_exhausted"


def test_trajectory_record_round_trips_through_jsonl(tmp_path):
    trajectory = _build("GB-BESS-EP-005", RuleBasedAgent(dt_hours=DT_HOURS))
    writer = TrajectoryJsonlWriter(tmp_path / "trajectories.jsonl")
    writer.write(trajectory)
    writer.write(trajectory)

    read_back = writer.read_all()
    assert len(read_back) == 2
    assert read_back[0] == trajectory
    assert len(read_back[0].steps) == len(trajectory.steps)
