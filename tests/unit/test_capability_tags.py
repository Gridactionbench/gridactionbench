"""Tests for capability (docs/benchmark/CAPABILITY_TAXONOMY.md) and stress-dimension
(docs/benchmark/STRESS_DIMENSIONS.md) tagging — added September 2026 strategic realignment,
closing docs/project/GAP_ANALYSIS.md's P1 tagging gap and guarding against
docs/project/RISK_REGISTER.md R-19 (tagging going unapplied to future additions).

These tests check that every evaluator and Task Family carries a valid tag, not that any
tag assignment is "correct" in some absolute sense — capability/stress-dimension
assignment is a documented judgment call (docs/benchmark/STRESS_DIMENSIONS.md, "Calibration
input, not calibration output"), reviewable but not itself computable.
"""

from __future__ import annotations

from gridactionbench.evaluators.base import Capability
from gridactionbench.evaluators.gb_bess import STANDARD_EVALUATORS
from gridactionbench.evaluators.gb_bess import adv, hum
from gridactionbench.scenarios.gb_bess.episodes import EPISODES
from gridactionbench.scenarios.generator import TEMPLATES

VALID_U_CLASSES = {f"U{i}" for i in range(8)}


def test_every_standard_evaluator_has_a_valid_primary_capability():
    for evaluator in STANDARD_EVALUATORS:
        assert isinstance(evaluator.primary_capability, Capability), evaluator.eval_id


def test_adv_and_hum_module_level_capability_constants_are_valid():
    assert isinstance(adv.PRIMARY_CAPABILITY, Capability)
    assert isinstance(hum.REQUIRED_ESCALATION_PRIMARY_CAPABILITY, Capability)
    assert isinstance(hum.UNNECESSARY_ESCALATION_PRIMARY_CAPABILITY, Capability)
    assert hum.REQUIRED_ESCALATION_SECONDARY_CAPABILITIES == (Capability.PERCEIVE,)


def test_evaluate_results_carry_the_evaluator_s_primary_capability():
    """A tag that never reaches EvaluationResult is exactly the "documentation-only
    decoration" docs/project/RISK_REGISTER.md R-19 warns against — spot-check one
    evaluator rather than re-running every branch already covered by
    tests/unit/test_evaluators.py."""
    from gridactionbench.core.scenario import EscalationSpec, Oracle, Scenario
    from gridactionbench.evaluators.base import Context
    from gridactionbench.evaluators.gb_bess.phy import PhyVoltageMax001
    from gridactionbench.schemas.action import ActionType, AgentActionV1
    from gridactionbench.simulators.psse_simulator import PSSESimulatorAdapter

    scenario = Scenario(
        scenario_id="TAG-CHECK-001",
        scenario_version="0.2.0",
        family="PHY",
        oracle=Oracle(
            network_model={
                "buses": [
                    {"bus_id": 1, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
                    {"bus_id": 2, "voltage_pu": 1.05, "voltage_min_pu": 0.5, "voltage_max_pu": 1.05},
                ],
                "branches": [
                    {"branch_id": "L1", "from_bus": 1, "to_bus": 2, "mva_flow": 10.0, "mva_limit": 1000.0, "sensitivity_mva_per_mw": 1.0}
                ],
                "generators": [
                    {
                        "bus_id": 2, "mw_output": 10.0, "mw_min": 0.0, "mw_max": 20.0,
                        "mw_ramp_up_limit_per_step": 20.0, "mw_ramp_down_limit_per_step": 20.0,
                        "voltage_sensitivity_pu_per_mw": 0.01,
                    }
                ],
            },
            operational_policy={
                "reserve_mw_margin": None,
                "temporary_limits": {"generation_increase_prohibited": False, "generation_decrease_prohibited": False},
                "approval_required": False,
            },
        ),
        escalation=EscalationSpec(required=False, permitted=True),
    )
    action = AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=15.0)
    observation = scenario.build_observation()
    post_state = PSSESimulatorAdapter().step(scenario.oracle.network_model, action, 0.5)
    ctx = Context(scenario=scenario, action=action, observation=observation, post_state=post_state, dt_hours=0.5)

    result = PhyVoltageMax001().evaluate(ctx)
    assert result.primary_capability is Capability.ACT


def test_every_scenario_template_has_valid_stress_dimension_and_capability_tags():
    for template in TEMPLATES:
        assert isinstance(template.primary_capability, Capability), template.template_id
        assert template.u_classes, template.template_id
        assert set(template.u_classes) <= VALID_U_CLASSES, template.template_id
        assert template.complexity_rung == "C0", template.template_id
        assert template.autonomy_burden == "low", template.template_id


AUTONOMY_BURDEN_BY_TASK_MODE = {"Sequential": "medium", "Operational": "high"}


def test_every_episode_has_valid_stress_dimension_and_capability_tags():
    for episode_id, (episode, _check_fn) in EPISODES.items():
        assert isinstance(episode.primary_capability, Capability), episode_id
        assert episode.u_classes, episode_id
        assert set(episode.u_classes) <= VALID_U_CLASSES, episode_id
        assert episode.complexity_rung == "C0", episode_id
        assert episode.task_mode in AUTONOMY_BURDEN_BY_TASK_MODE, episode_id
        assert episode.autonomy_burden == AUTONOMY_BURDEN_BY_TASK_MODE[episode.task_mode], episode_id


def test_episodes_naming_sequential_match_the_reclassification_finding():
    """docs/benchmark/TASK_MODEL.md: GB-BESS-EP-001 and EP-002 have no per-step condition
    change (only SOC threads forward) and were reclassified `task_mode="Sequential"` on
    2026-09-09, correcting the earlier claim that no GB-BESS task family occupied that
    rung. EP-003 onward genuinely vary a condition mid-episode and remain "Operational".
    This test pins that claim to the actual tags so the two cannot silently drift apart."""
    sequential_episodes = {
        episode_id for episode_id, (episode, _check_fn) in EPISODES.items() if episode.task_mode == "Sequential"
    }
    assert sequential_episodes == {"GB-BESS-EP-001", "GB-BESS-EP-002"}


def test_episodes_naming_adapt_as_primary_match_the_taxonomy_s_own_account():
    """docs/benchmark/CAPABILITY_TAXONOMY.md, "ADAPT": four of the seven existing episodes
    touch this — GB-BESS-EP-003, EP-004, EP-005 (changing conditions) and EP-007 (a
    forecast that turns out wrong, added 2026-09-09). This test pins that claim to the
    actual tags so the two cannot silently drift apart."""
    adapt_episodes = {
        episode_id for episode_id, (episode, _check_fn) in EPISODES.items() if episode.primary_capability is Capability.ADAPT
    }
    assert adapt_episodes == {"GB-BESS-EP-003", "GB-BESS-EP-004", "GB-BESS-EP-005", "GB-BESS-EP-007"}
