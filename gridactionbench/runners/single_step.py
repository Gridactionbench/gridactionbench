"""Mode A — Single-Step runner. See docs/benchmark/SPECIFICATION.md §2.

Scenario -> Observation -> Agent -> Action -> Validator -> Simulator -> Evaluation
-> Decision Record, per docs/architecture/ARCHITECTURE.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from gridactionbench.agents.base import AgentAdapter
from gridactionbench.core import engine as evaluation_engine
from gridactionbench.core.decision_record import (
    DecisionRecord,
    evaluation_result_to_dict,
    step_result_to_dict,
)
from gridactionbench.core.scenario import Scenario
from gridactionbench.provenance.capture import (
    capture_environment_metadata,
    capture_git_commit,
    capture_runtime_version,
)
from gridactionbench.schemas.action import AgentActionV1


def run_single_step(
    scenario: Scenario,
    agent: AgentAdapter,
    dt_hours: float,
    run_id: str | None = None,
    random_seed: int | None = None,
) -> DecisionRecord:
    run_id = run_id or str(uuid.uuid4())
    observation = scenario.build_observation()

    errors: list[str] = []
    action: AgentActionV1 | None = None
    schema_valid = True
    try:
        action = agent.act(observation)
    except Exception as exc:  # noqa: BLE001 — a malformed/erroring agent is a recorded
        # outcome, not a runner crash; see docs/architecture/adr/ADR-008.
        schema_valid = False
        errors.append(f"agent raised during act(): {exc!r}")

    if action is None:
        # Treated as an implicit ESCALATE-equivalent failure for evaluation purposes
        # (docs/architecture/adr/ADR-008) — no action was produced at all.
        return DecisionRecord(
            suite_version=scenario.suite_version,
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            scenario_version=scenario.scenario_version,
            scenario_source_type=scenario.source_type,
            task_family_tags=scenario.task_family_tags,
            agent_id=agent.agent_id,
            agent_version=agent.agent_version,
            agent_type=agent.agent_type,
            observation=observation,
            raw_agent_response=None,
            parsed_action=None,
            schema_valid=False,
            simulator_pre_state=scenario.oracle.network_model.model_dump(),
            simulator_post_state=None,
            evaluation_results=[],
            errors=errors,
            dt_hours=dt_hours,
            random_seed=random_seed,
            git_commit=capture_git_commit(),
            runtime_version=capture_runtime_version(),
            environment_metadata=capture_environment_metadata(),
            timestamp=datetime.now(timezone.utc),
        )

    outcome = evaluation_engine.evaluate(scenario, action, observation, dt_hours)

    return DecisionRecord(
        suite_version=scenario.suite_version,
        run_id=run_id,
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        scenario_source_type=scenario.source_type,
        task_family_tags=scenario.task_family_tags,
        agent_id=agent.agent_id,
        agent_version=agent.agent_version,
        agent_type=agent.agent_type,
        observation=observation,
        raw_agent_response=action.model_dump(mode="json"),
        parsed_action=action,
        schema_valid=schema_valid,
        simulator_pre_state=scenario.oracle.network_model.model_dump(),
        simulator_post_state=step_result_to_dict(outcome.post_state),
        evaluation_results=[evaluation_result_to_dict(r) for r in outcome.results],
        hard_constraint_valid=outcome.hard_constraint_valid,
        ucv=outcome.ucv,
        self_reported_high_confidence_ucv=outcome.self_reported_high_confidence_ucv,
        objective_value_achieved_gbp=outcome.objective_value.achieved_gbp,
        objective_value_best_case_gbp=outcome.objective_value.best_case_gbp,
        errors=errors,
        dt_hours=dt_hours,
        random_seed=random_seed,
        git_commit=capture_git_commit(),
        runtime_version=capture_runtime_version(),
        environment_metadata=capture_environment_metadata(),
        timestamp=datetime.now(timezone.utc),
    )
