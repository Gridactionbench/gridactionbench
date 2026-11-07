"""Unit + physical-invariant tests for PSSESimulatorAdapter.

See docs/suites/gb-bess/SPECIFICATION.md §9 (frozen conventions, power-flow revision) and
docs/testing/TEST_STRATEGY.md, "Physical invariants." Exercises the adapter exclusively
through the fake `psspy` double (tests/fakes/fake_psspy.py, installed automatically by
tests/conftest.py's autouse `fake_psspy` fixture) — see that fake's module docstring for
exactly what linear model it implements and why.
"""

from __future__ import annotations

import pytest

from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import NetworkModel
from gridactionbench.simulators.psse_simulator import EPSILON, PSSESimulatorAdapter
from tests.fakes.fake_psspy import K_VOLTAGE_PU_PER_MW

DT_HOURS = 0.5


def make_network(**gen_overrides) -> NetworkModel:
    gen = dict(
        bus_id=2, mw_output=10.0, mw_min=0.0, mw_max=20.0,
        mw_ramp_up_limit_per_step=20.0, mw_ramp_down_limit_per_step=20.0,
        voltage_sensitivity_pu_per_mw=0.01,
    )
    gen.update(gen_overrides)
    return NetworkModel(
        buses=[
            {"bus_id": 1, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
            {"bus_id": 2, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
        ],
        branches=[
            {
                "branch_id": "L1", "from_bus": 1, "to_bus": 2,
                "mva_flow": gen["mw_output"], "mva_limit": 1000.0, "sensitivity_mva_per_mw": 1.0, "baseline_mva": 0.0,
            }
        ],
        generators=[gen],
    )


@pytest.fixture
def sim() -> PSSESimulatorAdapter:
    return PSSESimulatorAdapter()


def test_set_generation_voltage_matches_canonical_equation(sim):
    network = make_network(mw_output=10.0)
    action = AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=14.0)
    result = sim.step(network, action, DT_HOURS)

    expected_voltage = 1.0 + K_VOLTAGE_PU_PER_MW * (14.0 - 10.0)
    assert result.bus_voltages_pu[2] == pytest.approx(expected_voltage)
    assert result.generator_outputs_mw[2] == pytest.approx(14.0)
    assert result.converged is True


def test_branch_loading_matches_declared_sensitivity(sim):
    network = make_network(mw_output=10.0)
    action = AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=14.0)
    result = sim.step(network, action, DT_HOURS)
    # sensitivity_mva_per_mw=1.0, baseline_mva=0.0 -> flow == solved generator output
    assert result.branch_loadings_mva["L1"] == pytest.approx(14.0)


def test_idle_produces_no_state_change(sim):
    network = make_network(mw_output=10.0)
    action = AgentActionV1(action=ActionType.IDLE)
    result = sim.step(network, action, DT_HOURS)
    assert result.bus_voltages_pu[2] == pytest.approx(1.0)
    assert result.generator_outputs_mw[2] == pytest.approx(10.0)


def test_negative_mw_is_rejected_by_schema():
    with pytest.raises(ValueError):
        AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=-1.0)


def test_idle_with_bus_id_is_rejected_by_schema():
    with pytest.raises(ValueError):
        AgentActionV1(action=ActionType.IDLE, bus_id=2)


def test_escalate_without_reason_code_is_rejected_by_schema():
    with pytest.raises(ValueError):
        AgentActionV1(action=ActionType.ESCALATE)


def test_set_generation_without_bus_id_is_rejected_by_schema():
    with pytest.raises(ValueError):
        AgentActionV1(action=ActionType.SET_GENERATION, mw=5.0)


# --- Physical invariants (docs/testing/TEST_STRATEGY.md, "Physical invariants") ---


def test_voltage_delta_is_linear_in_requested_mw_change(sim):
    network = make_network(mw_output=10.0)
    small = sim.step(network, AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=11.0), DT_HOURS)
    large = sim.step(network, AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=12.0), DT_HOURS)
    small_delta = small.bus_voltages_pu[2] - 1.0
    large_delta = large.bus_voltages_pu[2] - 1.0
    assert large_delta == pytest.approx(small_delta * 2.0)


def test_validate_action_rejects_outside_nameplate_limits(sim):
    network = make_network(mw_output=10.0, mw_min=2.0, mw_max=18.0)
    assert sim.validate_action(network, AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=18.0)) is True
    assert sim.validate_action(network, AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=18.1)) is False
    assert sim.validate_action(network, AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=1.9)) is False


def test_validate_action_passes_idle_and_escalate_through(sim):
    network = make_network()
    assert sim.validate_action(network, AgentActionV1(action=ActionType.IDLE)) is True
    assert sim.validate_action(network, AgentActionV1(action=ActionType.ESCALATE, reason_code="TOOL_FAILURE")) is True


def test_deterministic_reproducibility(sim):
    network = make_network(mw_output=7.3)
    action = AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=12.5)
    results = [sim.step(network, action, DT_HOURS, seed=42).bus_voltages_pu[2] for _ in range(5)]
    assert len(set(results)) == 1, "identical (network, action, dt_hours, seed) must be bit-identical across runs"
