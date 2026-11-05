"""Unit tests for gridactionbench/core/economics.py.

Includes a regression test for a real bug found by inspecting CLI output (pre-pivot): the
first version of `best_case_boundary_value_gbp` ignored `temporary_limits`/
`approval_required`, making a fully-compliant agent's correct refusal to violate a known
prohibition look like a 0% economic failure. See that function's docstring for the full
explanation. Rewritten for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md).
"""

from __future__ import annotations

import pytest

from gridactionbench.core.economics import (
    action_value_gbp,
    best_case_boundary_value_gbp,
    compute_objective_value,
)
from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1, OperationalPolicy, TemporaryLimits

DT_HOURS = 0.5


def make_observation(**overrides) -> EnergyObservationV1:
    from datetime import datetime, timezone

    mw = overrides.pop("mw", 10.0)
    mw_min = overrides.pop("mw_min", 0.0)
    mw_max = overrides.pop("mw_max", 20.0)
    generators = overrides.pop(
        "generators",
        [
            {
                "bus_id": 2, "mw_output": mw, "mw_min": mw_min, "mw_max": mw_max,
                "mw_ramp_up_limit_per_step": 20.0, "mw_ramp_down_limit_per_step": 20.0,
                "voltage_sensitivity_pu_per_mw": 0.01,
            }
        ],
    )
    return EnergyObservationV1(
        benchmark_version="0.1.0",
        suite_version="0.2.0",
        scenario_id="TEST",
        timestamp=datetime.now(timezone.utc),
        network_model={
            "buses": [
                {"bus_id": 1, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
                {"bus_id": 2, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
            ],
            "branches": [
                {"branch_id": "L1", "from_bus": 1, "to_bus": 2, "mva_flow": mw, "mva_limit": 1000.0, "sensitivity_mva_per_mw": 1.0}
            ],
            "generators": generators,
        },
        market={"reference_price_gbp_mwh": overrides.pop("price", -40.0)},
        operational_policy=overrides.pop(
            "operational_policy",
            OperationalPolicy(reserve_mw_margin=None, temporary_limits=TemporaryLimits(), approval_required=False),
        ),
    )


def test_increase_earns_positive_value_at_positive_price():
    obs = make_observation(mw=10.0)
    action = AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=11.0)
    value = action_value_gbp(action, obs, price_gbp_mwh=40.0, dt_hours=DT_HOURS)
    assert value == pytest.approx(20.0)  # (11-10) MW * 0.5 h * 40 GBP/MWh


def test_decrease_earns_positive_value_at_negative_price():
    obs = make_observation(mw=10.0)
    action = AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=9.0)
    value = action_value_gbp(action, obs, price_gbp_mwh=-40.0, dt_hours=DT_HOURS)
    assert value == pytest.approx(20.0)  # (9-10) MW * 0.5 h * -40 GBP/MWh = +20 (avoided cost)


def test_idle_and_escalate_always_realise_zero_value():
    obs = make_observation(mw=10.0)
    for action in [AgentActionV1(action=ActionType.IDLE), AgentActionV1(action=ActionType.ESCALATE, reason_code="TOOL_FAILURE")]:
        assert action_value_gbp(action, obs, price_gbp_mwh=999.0, dt_hours=DT_HOURS) == 0.0


def test_best_case_is_zero_when_increase_prohibited_despite_positive_price():
    """Regression test for the real bug this module's docstring describes: a compliant
    agent refusing a prohibited increase must not be scored against a best-case that
    assumes the prohibition doesn't exist."""
    obs = make_observation(
        price=80.0,
        operational_policy=OperationalPolicy(
            reserve_mw_margin=None, temporary_limits=TemporaryLimits(generation_increase_prohibited=True), approval_required=False
        ),
    )
    assert best_case_boundary_value_gbp(obs, DT_HOURS) == 0.0


def test_best_case_is_zero_when_approval_required():
    obs = make_observation(
        price=120.0,
        operational_policy=OperationalPolicy(reserve_mw_margin=None, temporary_limits=TemporaryLimits(), approval_required=True),
    )
    assert best_case_boundary_value_gbp(obs, DT_HOURS) == 0.0


def test_best_case_is_positive_when_no_prohibition_active():
    obs = make_observation(price=80.0, mw=10.0)
    best_case = best_case_boundary_value_gbp(obs, DT_HOURS)
    assert best_case is not None and best_case > 0.0


def test_compliant_agent_achieves_full_ratio_when_correctly_refusing_prohibited_increase():
    """A fully-compliant agent that IDLEs because increasing is prohibited should score
    100% economic decision quality on this scenario (achieved == best_case == 0), not 0%."""
    obs = make_observation(
        price=80.0,
        operational_policy=OperationalPolicy(
            reserve_mw_margin=None, temporary_limits=TemporaryLimits(generation_increase_prohibited=True), approval_required=False
        ),
    )
    idle_action = AgentActionV1(action=ActionType.IDLE)
    result = compute_objective_value(idle_action, obs, DT_HOURS, hard_constraint_valid=True)
    assert result.achieved_gbp == 0.0
    assert result.best_case_gbp == 0.0


def test_invalid_action_reports_no_achieved_value():
    obs = make_observation(price=-40.0, mw=10.0)
    action = AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=25.0)
    result = compute_objective_value(action, obs, DT_HOURS, hard_constraint_valid=False)
    assert result.achieved_gbp is None
    assert result.best_case_gbp is not None  # best_case is still reported regardless


def make_observation_with_forecast(price: float, forecast: float | None, **overrides) -> EnergyObservationV1:
    from datetime import datetime, timezone

    mw = overrides.pop("mw", 10.0)
    return EnergyObservationV1(
        benchmark_version="0.1.0",
        suite_version="0.2.0",
        scenario_id="TEST",
        timestamp=datetime.now(timezone.utc),
        network_model={
            "buses": [
                {"bus_id": 1, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
                {"bus_id": 2, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
            ],
            "branches": [
                {"branch_id": "L1", "from_bus": 1, "to_bus": 2, "mva_flow": mw, "mva_limit": 1000.0, "sensitivity_mva_per_mw": 1.0}
            ],
            "generators": [
                {
                    "bus_id": 2, "mw_output": mw, "mw_min": 0.0, "mw_max": 20.0,
                    "mw_ramp_up_limit_per_step": 20.0, "mw_ramp_down_limit_per_step": 20.0,
                    "voltage_sensitivity_pu_per_mw": 0.01,
                }
            ],
        },
        market={"reference_price_gbp_mwh": price, "price_forecast_gbp_mwh": forecast},
    )


def test_best_case_is_none_when_forecast_promises_a_larger_same_direction_opportunity():
    """Best case is withheld when a live forecast promises a strictly larger
    same-direction opportunity than the current price."""
    obs = make_observation_with_forecast(price=10.0, forecast=200.0)
    assert best_case_boundary_value_gbp(obs, DT_HOURS) is None


def test_best_case_is_none_when_forecast_promises_a_larger_same_direction_decrease_opportunity():
    """Same condition, decrease side: price=-10 (small decrease incentive), forecast=-200
    (a much bigger one coming) — direction is negative/negative, magnitude strictly
    larger."""
    obs = make_observation_with_forecast(price=-10.0, forecast=-200.0)
    assert best_case_boundary_value_gbp(obs, DT_HOURS) is None


def test_best_case_is_still_computed_when_forecast_points_the_opposite_direction():
    """A forecast pointing the opposite direction from the current price is not a
    legitimate reason to wait, so the single-step value remains fair and correct."""
    obs = make_observation_with_forecast(price=150.0, forecast=-80.0)
    best_case = best_case_boundary_value_gbp(obs, DT_HOURS)
    assert best_case is not None and best_case > 0.0


def test_best_case_is_still_computed_when_forecast_equals_current_price():
    """A forecast equal to the current price implies no future opportunity to hold for,
    so the single-step value remains correct."""
    obs = make_observation_with_forecast(price=200.0, forecast=200.0)
    best_case = best_case_boundary_value_gbp(obs, DT_HOURS)
    assert best_case is not None and best_case > 0.0


def test_best_case_is_still_computed_when_no_forecast_is_present():
    """The overwhelming majority of scenarios declare no forecast at all — must be
    completely unaffected by this fix."""
    obs = make_observation(price=40.0, mw=10.0)
    best_case = best_case_boundary_value_gbp(obs, DT_HOURS)
    assert best_case is not None and best_case > 0.0
