"""Calibration tests for the 7 seeded failure agents (master brief §27).

Each seeded agent has a documented expected failure mode (see its module docstring under
baselines/seeded_failures/). This file verifies each agent actually exhibits that failure
mode on the specific scenario it was designed to trip, and that the benchmark's UCV
machinery correctly detects it — this is what master brief §69/§72 call "confirm that
known failures are correctly detected" before any LLM comparison is credible.

Rewritten for the PSS/E power-flow pivot (docs/architecture/adr/ADR-018-psse-power-flow-adapter.md).
"""

from __future__ import annotations

from pathlib import Path

from baselines.seeded_failures.always_max_generation import AlwaysMaxGenerationAgent
from baselines.seeded_failures.ignore_reserve_margin import IgnoreReserveMarginAgent
from baselines.seeded_failures.ignore_thermal_limit import IgnoreThermalLimitAgent
from baselines.seeded_failures.never_escalate import NeverEscalateAgent
from baselines.seeded_failures.prompt_injection_victim import PromptInjectionVictimAgent
from baselines.seeded_failures.revenue_first_constraint_ignoring import RevenueFirstConstraintIgnoringAgent
from baselines.seeded_failures.trust_all_telemetry import TrustAllTelemetryAgent
from gridactionbench.core.scenario import load_scenario, load_scenario_dir
from gridactionbench.runners.single_step import run_single_step

SCENARIO_DIR = Path(__file__).resolve().parent.parent.parent / "suites" / "gb_bess" / "v0_1" / "scenarios"
DT_HOURS = 0.5


def eval_ids_that_failed(record) -> set[str]:
    return {r["eval_id"] for r in record.evaluation_results if r["result"] == "FAIL"}


def test_always_max_generation_agent_fails_phy_voltage_max_and_produces_ucv():
    scenario = load_scenario(SCENARIO_DIR / "GB-BESS-PHY-001.yaml")
    record = run_single_step(scenario, AlwaysMaxGenerationAgent(), DT_HOURS)
    assert "PHY-VOLTAGE-MAX-001" in eval_ids_that_failed(record)
    assert record.ucv is True


def test_ignore_thermal_limit_agent_fails_net_branch_thermal_limit_and_produces_ucv():
    scenario = load_scenario(SCENARIO_DIR / "GB-BESS-NET-007.yaml")
    record = run_single_step(scenario, IgnoreThermalLimitAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert "NET-BRANCH-THERMAL-LIMIT-001" in eval_ids_that_failed(record)
    assert record.ucv is True


def test_ignore_reserve_margin_agent_fails_ops_reserve_mw_margin_and_produces_ucv():
    scenario = load_scenario(SCENARIO_DIR / "GB-BESS-OPS-011.yaml")
    record = run_single_step(scenario, IgnoreReserveMarginAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert "OPS-RESERVE-MW-MARGIN-001" in eval_ids_that_failed(record)
    assert record.ucv is True


def test_revenue_first_agent_fails_ops_temp_decrease_prohibition_and_produces_ucv():
    scenario = load_scenario(SCENARIO_DIR / "GB-BESS-OPS-012.yaml")
    record = run_single_step(scenario, RevenueFirstConstraintIgnoringAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert "OPS-TEMP-GENERATION-DECREASE-PROHIBITION-001" in eval_ids_that_failed(record)
    assert record.ucv is True


def test_trust_all_telemetry_agent_fails_on_implausible_branch_loading_with_high_confidence_ucv():
    scenario = load_scenario(SCENARIO_DIR / "GB-BESS-DATA-017.yaml")
    record = run_single_step(scenario, TrustAllTelemetryAgent(dt_hours=DT_HOURS), DT_HOURS)
    failed = eval_ids_that_failed(record)
    assert "DATA-IMPLAUSIBLE-BRANCH-LOADING-001" in failed or "NET-BRANCH-THERMAL-LIMIT-001" in failed
    assert record.ucv is True
    assert record.self_reported_high_confidence_ucv is True


def test_never_escalate_agent_passes_ops_approval_but_fails_hum_required_escalation():
    """The concrete demonstration of why OPS-APPROVAL-REQUIRED-001 alone is not
    UCV-eligible: this agent's IDLE default is *accepted* by that evaluator, yet the
    benchmark still correctly detects the underlying failure via the HUM evaluator."""
    scenario = load_scenario(SCENARIO_DIR / "GB-BESS-OPS-013.yaml")
    record = run_single_step(scenario, NeverEscalateAgent(dt_hours=DT_HOURS), DT_HOURS)
    results_by_id = {r["eval_id"]: r for r in record.evaluation_results}
    assert results_by_id["OPS-APPROVAL-REQUIRED-001"]["result"] == "PASS"
    hum_required = next(r for eid, r in results_by_id.items() if eid.endswith("required_escalation"))
    assert hum_required["result"] == "FAIL"
    assert record.ucv is True


def test_prompt_injection_victim_agent_fails_adv_instruction_override_and_produces_ucv():
    scenario = load_scenario(SCENARIO_DIR / "GB-BESS-ADV-018.yaml")
    record = run_single_step(scenario, PromptInjectionVictimAgent(dt_hours=DT_HOURS), DT_HOURS)
    assert "ADV-INSTRUCTION-OVERRIDE-001" in eval_ids_that_failed(record)
    assert record.ucv is True


def test_every_seeded_agent_produces_at_least_one_ucv_across_the_suite():
    """Basic sanity sweep: each seeded failure agent must be demonstrably defective
    somewhere across the 20 initial scenarios — a seeded agent producing zero UCVs would
    indicate either the agent isn't actually defective as documented, or the benchmark
    failed to detect a known failure mode (master brief §72)."""
    scenarios = load_scenario_dir(SCENARIO_DIR)
    agents = {
        "always-max-generation": AlwaysMaxGenerationAgent(),
        "ignore-thermal-limit": IgnoreThermalLimitAgent(dt_hours=DT_HOURS),
        "ignore-reserve-margin": IgnoreReserveMarginAgent(dt_hours=DT_HOURS),
        "revenue-first-constraint-ignoring": RevenueFirstConstraintIgnoringAgent(dt_hours=DT_HOURS),
        "trust-all-telemetry": TrustAllTelemetryAgent(dt_hours=DT_HOURS),
        "never-escalate": NeverEscalateAgent(dt_hours=DT_HOURS),
        "prompt-injection-victim": PromptInjectionVictimAgent(dt_hours=DT_HOURS),
    }
    for name, agent in agents.items():
        ucv_total = sum(1 for scenario in scenarios if run_single_step(scenario, agent, DT_HOURS).ucv)
        assert ucv_total > 0, f"{name} produced zero UCVs across the initial 20 scenarios — expected at least one"
