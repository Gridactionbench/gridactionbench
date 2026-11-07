"""Tests for the reporting layer (gridactionbench/reporting/report.py).

See docs/benchmark/SCORING.md and docs/benchmark/STRESS_DIMENSIONS.md, "How C/U/H
metadata should be used once tagged" — added September 2026 strategic realignment,
closing docs/project/GAP_ANALYSIS.md's P1 item 3 (reporting-layer slicing by the
capability/stress-dimension tags added in the previous pass). No reporting tests existed
before this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gridactionbench.core.decision_record import DecisionRecord
from gridactionbench.core.scenario import EscalationSpec, Oracle, Scenario, TaskFamilyTags
from gridactionbench.reporting.report import build_report, render_text

DT_HOURS = 0.5


def _scenario(scenario_id: str) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        scenario_version="0.2.0",
        family="PHY",
        oracle=Oracle(
            network_model={
                "buses": [
                    {"bus_id": 1, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
                    {"bus_id": 2, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
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


def _eval_result(eval_id: str, result: str, constraint_class: str | None, ucv_eligible: bool, primary_capability: str | None) -> dict:
    return {
        "eval_id": eval_id,
        "version": "0.1.0",
        "constraint_class": constraint_class,
        "severity": "CRITICAL",
        "ucv_eligible": ucv_eligible,
        "result": result,
        "evidence": {},
        "contributes_to_ucv": result == "FAIL" and ucv_eligible,
        "primary_capability": primary_capability,
        "secondary_capabilities": [],
    }


def _record(
    scenario_id: str,
    evaluation_results: list[dict],
    ucv: bool = False,
    task_family_tags: TaskFamilyTags | None = None,
) -> DecisionRecord:
    scenario = _scenario(scenario_id)
    return DecisionRecord(
        suite_version="0.1.0",
        run_id="test-run",
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        scenario_source_type=scenario.source_type,
        task_family_tags=task_family_tags,
        agent_id="test-agent",
        agent_version="0.1.0",
        agent_type="test",
        observation=scenario.build_observation(),
        schema_valid=True,
        simulator_pre_state=scenario.oracle.network_model.model_dump(),
        evaluation_results=evaluation_results,
        ucv=ucv,
        dt_hours=DT_HOURS,
        runtime_version="0.1.0",
        timestamp=datetime.now(timezone.utc),
    )


def test_by_capability_tallies_pass_and_fail_independent_of_family():
    record = _record(
        "R1",
        [
            _eval_result("PHY-VOLTAGE-MAX-001", "PASS", "HARD", True, "ACT"),
            _eval_result("DATA-MISSING-VOLTAGE-001", "FAIL", "INFORMATION", True, "PERCEIVE"),
        ],
    )
    report = build_report([record])
    assert report.by_capability["ACT"].pass_count == 1
    assert report.by_capability["PERCEIVE"].fail_count == 1
    assert report.by_capability["ACT"].pass_rate == 1.0
    assert report.by_capability["PERCEIVE"].pass_rate == 0.0


def test_evaluation_result_missing_primary_capability_does_not_crash_or_get_tallied():
    record = _record("R1", [_eval_result("ADV-INSTRUCTION-OVERRIDE-001", "PASS", None, True, None)])
    report = build_report([record])
    assert report.by_capability == {}


def test_ucv_by_u_class_counts_toward_every_declared_class():
    tags = TaskFamilyTags(task_mode="Atomic", primary_capability="PERCEIVE", complexity_rung="C0", u_classes=("U2", "U4"), autonomy_burden="low")
    record = _record("R1", [_eval_result("DATA-CONFLICT-VOLTAGE-001", "FAIL", "INFORMATION", True, "PERCEIVE")], ucv=True, task_family_tags=tags)
    report = build_report([record])
    assert report.ucv_by_u_class == {"U2": 1, "U4": 1}
    assert report.ucv_by_complexity_rung == {"C0": 1}
    assert report.ucv_by_autonomy_burden == {"low": 1}


def test_untagged_scenario_contributes_nothing_to_stress_dimension_breakdowns_even_with_a_ucv():
    """Scenario.task_family_tags is None for the 20 hand-authored v0.1 scenarios — a UCV
    against one of those must not silently appear under some default bucket."""
    record = _record("GB-BESS-PHY-001", [_eval_result("PHY-VOLTAGE-MAX-001", "FAIL", "HARD", True, "ACT")], ucv=True, task_family_tags=None)
    report = build_report([record])
    assert report.ucv_count == 1
    assert report.ucv_by_u_class == {}
    assert report.ucv_by_complexity_rung == {}
    assert report.ucv_by_autonomy_burden == {}


def test_non_ucv_record_does_not_populate_stress_dimension_breakdowns_even_if_tagged():
    tags = TaskFamilyTags(task_mode="Atomic", primary_capability="ACT", complexity_rung="C0", u_classes=("U0",), autonomy_burden="low")
    record = _record("R1", [_eval_result("PHY-VOLTAGE-MAX-001", "PASS", "HARD", True, "ACT")], ucv=False, task_family_tags=tags)
    report = build_report([record])
    assert report.ucv_by_u_class == {}


def test_render_text_includes_by_capability_section_only_when_non_empty():
    tagged = build_report([_record("R1", [_eval_result("PHY-VOLTAGE-MAX-001", "PASS", "HARD", True, "ACT")])])
    assert "By capability" in render_text(tagged)

    untagged = build_report([_record("R1", [])])
    assert "By capability" not in render_text(untagged)


def test_render_text_includes_stress_dimension_breakdown_lines():
    tags = TaskFamilyTags(task_mode="Atomic", primary_capability="PERCEIVE", complexity_rung="C0", u_classes=("U2",), autonomy_burden="low")
    report = build_report([_record("R1", [_eval_result("DATA-MISSING-VOLTAGE-001", "FAIL", "INFORMATION", True, "PERCEIVE")], ucv=True, task_family_tags=tags)])
    text = render_text(report)
    assert "by u_class: U2 1" in text
    assert "by complexity_rung: C0 1" in text
    assert "by autonomy_burden: low 1" in text
