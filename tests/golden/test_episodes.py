"""Calibration tests for the 8 GB-BESS episodes (Mode B). See docs/suites/gb-bess/
SCENARIO_CATALOGUE.md, "Episode scenarios," and docs/architecture/adr/
ADR-016-episode-architecture.md.

Each episode's failure_signature check is verified bidirectionally: RuleBasedAgent (the
transparent, compliant reference controller) must never trigger it, and at least one
seeded failure agent whose documented defect matches the episode's design intent must
trigger it reliably. A failure_signature that never triggers for any agent would be a
dead check; a failure_signature that triggers even for a compliant agent would be a false
positive — both are equally important to rule out.

GB-BESS-EP-008 is the one deliberate exception: it exists specifically to demonstrate a
real, already-disclaimed limitation of RuleBasedAgent (docs/project/ASSUMPTIONS.md A-12:
"not claimed to be an economically optimal... trading strategy") — a genuine multi-step
timing tradeoff where its greedy per-step policy is provably suboptimal. RuleBasedAgent is
*expected* to trigger it; MpcLookaheadAgent (baselines/mpc_lookahead/agent.py), built
specifically to solve this tradeoff, is expected not to — verified explicitly below rather
than folded into the generic sweep.

Rewritten for the PSS/E power-flow pivot (docs/architecture/adr/ADR-018-psse-power-flow-adapter.md).
"""

from __future__ import annotations

from baselines.always_escalate.agent import AlwaysEscalateAgent
from baselines.mpc_lookahead.agent import MpcLookaheadAgent
from baselines.rule_based.agent import RuleBasedAgent
from baselines.seeded_failures.always_max_generation import AlwaysMaxGenerationAgent
from baselines.seeded_failures.ignore_reserve_margin import IgnoreReserveMarginAgent
from baselines.seeded_failures.ignore_thermal_limit import IgnoreThermalLimitAgent
from baselines.seeded_failures.never_escalate import NeverEscalateAgent
from baselines.seeded_failures.revenue_first_constraint_ignoring import RevenueFirstConstraintIgnoringAgent
from baselines.seeded_failures.trust_all_telemetry import TrustAllTelemetryAgent
from baselines.seeded_failures.trust_forecast_over_actual import TrustForecastOverActualAgent
from gridactionbench.core.episode import run_episode
from gridactionbench.scenarios.gb_bess.episodes import EPISODES

DT_HOURS = 0.5

# The one deliberate exception to "RuleBasedAgent never triggers any episode failure
# signature" — see module docstring and check_ep008's own docstring
# (gridactionbench/scenarios/gb_bess/episodes.py).
EPISODES_WHERE_RULE_BASED_AGENT_IS_EXPECTED_TO_TRIGGER = {"GB-BESS-EP-008"}


def test_every_episode_step_produces_a_complete_decision_record():
    agent = RuleBasedAgent(dt_hours=DT_HOURS)
    for episode_id, (spec, _check) in EPISODES.items():
        result = run_episode(spec, agent, DT_HOURS)
        assert len(result.step_records) == spec.steps
        for record in result.step_records:
            assert record.schema_valid is True
            assert record.errors == []


def test_rule_based_agent_never_triggers_any_episode_failure_signature():
    agent = RuleBasedAgent(dt_hours=DT_HOURS)
    for episode_id, (spec, check) in EPISODES.items():
        if episode_id in EPISODES_WHERE_RULE_BASED_AGENT_IS_EXPECTED_TO_TRIGGER:
            continue
        result = run_episode(spec, agent, DT_HOURS)
        signature = check(result)
        assert not signature.triggered, f"{episode_id}: unexpected trigger — {signature.detail}"


def test_ep001_progressive_depletion_triggers_for_ignore_reserve_margin_agent():
    spec, check = EPISODES["GB-BESS-EP-001"]
    result = run_episode(spec, IgnoreReserveMarginAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_ep002_voltage_ceiling_approach_triggers_for_always_max_generation_agent():
    spec, check = EPISODES["GB-BESS-EP-002"]
    result = run_episode(spec, AlwaysMaxGenerationAgent(), DT_HOURS)
    assert check(result).triggered


def test_ep003_thermal_limit_change_triggers_for_ignore_thermal_limit_agent():
    spec, check = EPISODES["GB-BESS-EP-003"]
    result = run_episode(spec, IgnoreThermalLimitAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_ep004_telemetry_degradation_triggers_for_trust_all_telemetry_agent():
    spec, check = EPISODES["GB-BESS-EP-004"]
    result = run_episode(spec, TrustAllTelemetryAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_ep004_telemetry_degradation_triggers_for_never_escalate_agent():
    """Regression test: NeverEscalateAgent defaults to IDLE instead of escalating once
    telemetry goes stale at step 3, which check_ep004 must detect via the
    required-escalation failure signature."""
    spec, check = EPISODES["GB-BESS-EP-004"]
    result = run_episode(spec, NeverEscalateAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_ep005_temporary_restriction_triggers_for_revenue_first_agent():
    spec, check = EPISODES["GB-BESS-EP-005"]
    result = run_episode(spec, RevenueFirstConstraintIgnoringAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_ep006_repeated_escalation_triggers_for_never_escalate_agent():
    spec, check = EPISODES["GB-BESS-EP-006"]
    result = run_episode(spec, NeverEscalateAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_ep006_repeated_escalation_also_triggers_for_always_escalate_agent():
    """The other direction of EP-006's discrimination check — always escalating is
    exactly as much a failure as never escalating, per master brief §22."""
    spec, check = EPISODES["GB-BESS-EP-006"]
    result = run_episode(spec, AlwaysEscalateAgent(), DT_HOURS)
    assert check(result).triggered


def test_ep007_forecast_reversal_triggers_for_trust_forecast_over_actual_agent():
    spec, check = EPISODES["GB-BESS-EP-007"]
    result = run_episode(spec, TrustForecastOverActualAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_invalid_action_does_not_advance_episode_state():
    """Regression test for a real bug: the first version of run_episode() carried the
    simulator's hypothetical post-state generator output forward even when the action was
    hard-constraint-invalid, which could drive it outside its own physical limits and
    crash the next step's schema validation. An invalid action must leave the world state
    unchanged (docs/suites/gb-bess/SPECIFICATION.md §9.9)."""
    spec, _check = EPISODES["GB-BESS-EP-001"]
    result = run_episode(spec, IgnoreReserveMarginAgent(dt_hours=DT_HOURS), DT_HOURS)
    for record in result.step_records:
        # mw_min's pydantic constraint alone guarantees generator output stayed
        # non-negative for every step's Oracle to have validated at all, but check
        # explicitly too.
        assert record.observation.network_model.generators[0].mw_output >= 0.0


def test_ep008_two_peak_price_triggers_for_rule_based_agent():
    """The documented, expected exception (see module docstring) — RuleBasedAgent's greedy
    per-step policy is provably suboptimal on this specific timing tradeoff."""
    spec, check = EPISODES["GB-BESS-EP-008"]
    result = run_episode(spec, RuleBasedAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert check(result).triggered


def test_ep008_two_peak_price_does_not_trigger_for_mpc_lookahead_agent():
    """The new agent, built specifically to solve this tradeoff, must not trigger it —
    completing the bidirectional verification as "naive reference fails, smarter reference
    passes" rather than the usual "compliant agent passes, seeded failure fails" pairing."""
    spec, check = EPISODES["GB-BESS-EP-008"]
    result = run_episode(spec, MpcLookaheadAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert not check(result).triggered


def test_ep008_mpc_lookahead_agent_captures_more_revenue_than_rule_based_agent():
    """The real, numeric demonstration behind the binary trigger check above — verified by
    running both agents through the actual simulator. Unlike the pre-pivot battery-storage
    version of this episode (which proved an exact 2x figure via finite stored-energy
    scarcity — a mechanism a stateless generator doesn't have, see
    gridactionbench/scenarios/gb_bess/episodes.py's module docstring), the mechanism here
    is ceiling saturation: RuleBasedAgent spends its entire ramp budget reacting to the
    modest early price and is already at nameplate by the time the real peak arrives,
    capturing nothing further; MpcLookaheadAgent holds costlessly (no scarcity penalty for
    waiting) and captures the full peak. The resulting gap (75 GBP vs. 1500 GBP) is larger
    than the old exact-2x figure, not smaller, but it is a different mechanism and is
    reported as a measured fact, not a designed-in exact ratio."""
    spec, _check = EPISODES["GB-BESS-EP-008"]
    rule_based_result = run_episode(spec, RuleBasedAgent(dt_hours=DT_HOURS), DT_HOURS)
    mpc_result = run_episode(spec, MpcLookaheadAgent(dt_hours=DT_HOURS), DT_HOURS)

    def total_achieved_gbp(result):
        return sum(r.objective_value_achieved_gbp or 0.0 for r in result.step_records)

    rule_based_revenue = total_achieved_gbp(rule_based_result)
    mpc_revenue = total_achieved_gbp(mpc_result)
    assert round(rule_based_revenue, 2) == 75.0
    assert round(mpc_revenue, 2) == 1500.0
    assert mpc_revenue > rule_based_revenue


def test_mpc_lookahead_agent_behaves_identically_to_rule_based_agent_on_ep007():
    """The lookahead branch must never trigger on a forecast that turns out WRONG
    (GB-BESS-EP-007) — only on one that promises a genuinely better same-direction
    opportunity (GB-BESS-EP-008). Confirms MpcLookaheadAgent's one behavioural difference
    from RuleBasedAgent is contained to EP-008, not a side effect elsewhere."""
    spec, _check = EPISODES["GB-BESS-EP-007"]
    rule_based_result = run_episode(spec, RuleBasedAgent(dt_hours=DT_HOURS), DT_HOURS)
    mpc_result = run_episode(spec, MpcLookaheadAgent(dt_hours=DT_HOURS), DT_HOURS)
    rule_based_actions = [r.parsed_action.action for r in rule_based_result.step_records]
    mpc_actions = [r.parsed_action.action for r in mpc_result.step_records]
    assert rule_based_actions == mpc_actions
