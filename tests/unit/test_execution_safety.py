"""Regression tests for untrusted actions and failed solver results."""
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from gridactionbench.core.engine import evaluate
from gridactionbench.core.scenario import Oracle, Scenario
from gridactionbench.reporting.report import build_report, render_text
from gridactionbench.runners.single_step import run_single_step
from gridactionbench.schemas.action import AgentActionV1
from gridactionbench.schemas.observation import NetworkModel
from gridactionbench.simulators.base import PowerFlowStepResult
from gridactionbench.simulators.psspy_client import PsseSolveError
from tests.unit.test_simulator import make_network


def scenario():
    return Scenario(scenario_id="SAFETY", scenario_version="test", family="PHY",
                    oracle=Oracle(network_model=make_network()))


def agent(action):
    return Mock(agent_id="test", agent_version="test", agent_type="test",
                act=Mock(return_value=action))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_setpoints_and_network_values_are_rejected(value):
    with pytest.raises(ValidationError):
        AgentActionV1(action="SET_GENERATION", bus_id=2, mw=value)
    data = make_network().model_dump()
    data["generators"][0]["mw_output"] = value
    with pytest.raises(ValidationError):
        NetworkModel(**data)


def test_json_nan_is_rejected():
    with pytest.raises(ValidationError):
        AgentActionV1.model_validate_json('{"action":"SET_GENERATION","bus_id":2,"mw":NaN}')


def test_in_process_mutation_cannot_bypass_validation():
    action = AgentActionV1(action="SET_GENERATION", bus_id=2, mw=10)
    action.mw = float("nan")
    record = run_single_step(scenario(), agent(action), 0.5)
    assert not record.schema_valid
    assert record.evaluation_status == "agent_error"
    assert not record.hard_constraint_valid


def test_unknown_bus_is_a_recorded_invalid_action():
    record = run_single_step(scenario(), agent(AgentActionV1(
        action="SET_GENERATION", bus_id=999, mw=10)), 0.5)
    assert record.schema_valid
    assert record.evaluation_status == "invalid_action"
    assert record.simulator_post_state is None
    assert not record.hard_constraint_valid


def test_failed_solve_does_not_read_or_score_invalid_state(fake_psspy, monkeypatch):
    monkeypatch.setattr(fake_psspy, "fnsl", lambda options: 1)
    read = Mock(side_effect=AssertionError("must not read after a failed solve"))
    monkeypatch.setattr(fake_psspy, "busdat", read)
    record = run_single_step(scenario(), agent(AgentActionV1(action="IDLE")), 0.5)
    assert record.evaluation_status == "simulation_error"
    assert not record.hard_constraint_valid
    assert record.evaluation_results == []
    assert record.objective_value_achieved_gbp is None
    assert not record.ucv  # Solver failures are not proven agent violations.
    assert not read.called
    assert "simulation_error" in render_text(build_report([record]))


def test_api_success_does_not_imply_solver_convergence(fake_psspy, monkeypatch):
    monkeypatch.setattr(fake_psspy, "solved", lambda: 1)
    record = run_single_step(scenario(), agent(AgentActionV1(action="IDLE")), 0.5)
    assert record.evaluation_status == "simulation_error"
    assert not record.hard_constraint_valid


def test_vendor_api_exception_is_recorded(fake_psspy, monkeypatch):
    monkeypatch.setattr(fake_psspy, "psseinit", Mock(side_effect=TypeError("API mismatch")))
    record = run_single_step(scenario(), agent(AgentActionV1(action="IDLE")), 0.5)
    assert record.evaluation_status == "simulation_error"
    assert record.errors


@pytest.mark.parametrize("state", [
    PowerFlowStepResult(converged=False),
    PowerFlowStepResult(converged=True),
    PowerFlowStepResult(converged=True, bus_voltages_pu={1: 1, 2: float("nan")},
        branch_loadings_mva={"L1": 10}, generator_outputs_mw={2: 10}),
])
def test_custom_simulator_cannot_return_unscoreable_state(state):
    s = scenario()
    simulator = Mock(step=Mock(return_value=state))
    with pytest.raises(PsseSolveError):
        evaluate(s, AgentActionV1(action="IDLE"), s.build_observation(), 0.5, simulator)


@pytest.mark.parametrize("change", ["duplicate_bus", "duplicate_generator", "unknown_branch", "unknown_generator"])
def test_network_references_are_validated(change):
    data = make_network().model_dump()
    if change == "duplicate_bus":
        data["buses"].append(data["buses"][0])
    elif change == "duplicate_generator":
        data["generators"].append(data["generators"][0])
    elif change == "unknown_branch":
        data["branches"][0]["to_bus"] = 999
    else:
        data["generators"][0]["bus_id"] = 999
    with pytest.raises(ValidationError):
        NetworkModel(**data)


@pytest.mark.parametrize("dt", [0, -1, float("nan"), float("inf")])
def test_invalid_timestep_is_an_operator_error(dt):
    with pytest.raises(ValueError, match="dt_hours"):
        run_single_step(scenario(), agent(AgentActionV1(action="IDLE")), dt)
