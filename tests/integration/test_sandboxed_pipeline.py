"""Integration test: the sandbox boundary changes isolation, not scoring.

Runs the same scenario through RuleBasedAgent in-process, and through that same
RuleBasedAgent's decision logic wrapped inside SandboxedAgentAdapter (via the fake
backend, which executes the wrapped logic after a real JSON serialize/deserialize round
trip — the actual crossing a real sandbox would impose). The two must produce identical
evaluation results, proving the sandbox adds isolation without silently changing what
gets evaluated. See docs/architecture/adr/ADR-019-agent-execution-sandbox.md.
"""

from __future__ import annotations

from pathlib import Path

from baselines.rule_based.agent import RuleBasedAgent
from gridactionbench.agents.sandboxed import SandboxedAgentAdapter
from gridactionbench.core.scenario import load_scenario_dir
from gridactionbench.runners.single_step import run_single_step
from gridactionbench.schemas.action import AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1
from tests.fakes.fake_sandbox_backend import FakeSandboxBackend

SCENARIO_DIR = Path(__file__).resolve().parent.parent.parent / "suites" / "gb_bess" / "v0_1" / "scenarios"
DT_HOURS = 0.5


def _make_sandboxed_rule_based_agent() -> SandboxedAgentAdapter:
    real_agent = RuleBasedAgent(dt_hours=DT_HOURS)

    def agent_fn(observation_json: str) -> str:
        observation = EnergyObservationV1.model_validate_json(observation_json)
        action = real_agent.act(observation)
        return action.model_dump_json()

    backend = FakeSandboxBackend(agent_fn)
    return SandboxedAgentAdapter(backend=backend, agent_id="rule-based-sandboxed", agent_version=real_agent.agent_version)


def test_sandboxed_agent_produces_identical_results_to_in_process_agent():
    scenarios = load_scenario_dir(SCENARIO_DIR)
    in_process_agent = RuleBasedAgent(dt_hours=DT_HOURS)
    sandboxed_agent = _make_sandboxed_rule_based_agent()

    for scenario in scenarios:
        in_process_record = run_single_step(scenario, in_process_agent, DT_HOURS)
        sandboxed_record = run_single_step(scenario, sandboxed_agent, DT_HOURS)

        assert in_process_record.schema_valid == sandboxed_record.schema_valid
        assert in_process_record.hard_constraint_valid == sandboxed_record.hard_constraint_valid
        assert in_process_record.ucv == sandboxed_record.ucv
        assert [r["result"] for r in in_process_record.evaluation_results] == [
            r["result"] for r in sandboxed_record.evaluation_results
        ], scenario.scenario_id
        assert in_process_record.parsed_action.model_dump() == sandboxed_record.parsed_action.model_dump()
