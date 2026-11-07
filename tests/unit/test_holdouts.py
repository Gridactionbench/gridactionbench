"""Tests for the private-seed holdout generation infrastructure
(gridactionbench/holdouts/) — added September 2026 strategic realignment, closing part of
docs/project/GAP_ANALYSIS.md's P1 item 6 (docs/benchmark/PUBLIC_PRIVATE_POLICY.md).

Every test here uses an explicit, non-secret test seed passed directly to
generate_holdouts()/check_acceptance() — never through resolve_private_seed(), whose own
env-var/local-file resolution is tested separately and in isolation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from gridactionbench import holdouts
from gridactionbench.core.decision_record import DecisionRecord
from gridactionbench.core.scenario import EscalationSpec, Oracle, Scenario
from gridactionbench.holdouts.acceptance import check_acceptance
from gridactionbench.holdouts.generate import generate_holdouts
from gridactionbench.holdouts.private_seed import PrivateSeedNotConfigured, resolve_private_seed
from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.scenarios.generator import TEMPLATES

DT_HOURS = 0.5


def _scenario(scenario_id: str = "TEST", price: float = 40.0) -> Scenario:
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
            market={"reference_price_gbp_mwh": price},
            operational_policy={
                "reserve_mw_margin": None,
                "temporary_limits": {"generation_increase_prohibited": False, "generation_decrease_prohibited": False},
                "approval_required": False,
            },
        ),
        escalation=EscalationSpec(required=False, permitted=True),
    )


def _fake_record(scenario: Scenario, **overrides) -> DecisionRecord:
    defaults = dict(
        suite_version="0.1.0",
        run_id="test",
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        scenario_source_type=scenario.source_type,
        agent_id="test-agent",
        agent_version="0.1.0",
        agent_type="test",
        observation=scenario.build_observation(),
        schema_valid=True,
        simulator_pre_state=scenario.oracle.network_model.model_dump(),
        dt_hours=DT_HOURS,
        runtime_version="0.1.0",
        timestamp=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return DecisionRecord(**defaults)


# --- private_seed.py ---


def test_resolve_private_seed_raises_when_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("GRIDACTIONBENCH_PRIVATE_SEED", raising=False)
    monkeypatch.setattr("gridactionbench.holdouts.private_seed.LOCAL_SEED_FILE", tmp_path / "does_not_exist.txt")
    with pytest.raises(PrivateSeedNotConfigured):
        resolve_private_seed()


def test_resolve_private_seed_reads_env_var(monkeypatch):
    monkeypatch.setenv("GRIDACTIONBENCH_PRIVATE_SEED", "13579")
    assert resolve_private_seed() == 13579


def test_resolve_private_seed_rejects_non_integer_env_var(monkeypatch):
    monkeypatch.setenv("GRIDACTIONBENCH_PRIVATE_SEED", "not-an-integer")
    with pytest.raises(PrivateSeedNotConfigured):
        resolve_private_seed()


def test_resolve_private_seed_falls_back_to_local_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GRIDACTIONBENCH_PRIVATE_SEED", raising=False)
    seed_file = tmp_path / "private_seed.txt"
    seed_file.write_text("2468\n", encoding="utf-8")
    monkeypatch.setattr("gridactionbench.holdouts.private_seed.LOCAL_SEED_FILE", seed_file)
    assert resolve_private_seed() == 2468


# --- acceptance.py ---


def test_check_acceptance_accepts_a_well_formed_scenario():
    result = check_acceptance(_scenario())
    assert result.accepted
    assert result.reasons == []


def test_check_acceptance_rejects_on_agent_error(monkeypatch):
    scenario = _scenario()
    errored_record = _fake_record(scenario, errors=["agent raised during act(): boom"])
    monkeypatch.setattr("gridactionbench.holdouts.acceptance.run_single_step", lambda *a, **kw: errored_record)
    result = check_acceptance(scenario)
    assert not result.accepted
    assert any("errored" in reason for reason in result.reasons)


def test_check_acceptance_rejects_when_hard_constraint_invalid(monkeypatch):
    scenario = _scenario()
    bad_record = _fake_record(
        scenario,
        parsed_action=AgentActionV1(action=ActionType.SET_GENERATION, bus_id=2, mw=25.0),
        simulator_post_state={"converged": True, "bus_voltages_pu": {2: 1.3}, "branch_loadings_mva": {"L1": 25.0}, "generator_outputs_mw": {2: 25.0}},
        hard_constraint_valid=False,
    )
    monkeypatch.setattr("gridactionbench.holdouts.acceptance.run_single_step", lambda *a, **kw: bad_record)
    result = check_acceptance(scenario)
    assert not result.accepted
    assert any("self-contradictory" in reason for reason in result.reasons)


def test_sensitivity_flag_true_when_price_is_near_the_increase_decrease_crossover():
    # price=0.5: the 2%-of-magnitude perturbation is tiny (0.01), so the additive floor
    # (£1) dominates, crossing zero in the negative direction and flipping the requested
    # mw from an increase to a decrease (both SET_GENERATION — see
    # acceptance.py's model_dump-based comparison).
    result = check_acceptance(_scenario(price=0.5))
    assert result.sensitivity_flagged


def test_sensitivity_flag_false_when_price_is_far_from_any_threshold():
    result = check_acceptance(_scenario(price=-500.0))
    assert not result.sensitivity_flagged


# --- generate.py ---


def test_generate_holdouts_writes_a_manifest_and_accepted_instances(tmp_path):
    summary = generate_holdouts(private_seed=999, n_per_template=2, output_dir=tmp_path)
    assert summary.candidates_generated == len(TEMPLATES) * 2
    assert summary.accepted + summary.rejected == summary.candidates_generated

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["private_seed"] == 999
    assert manifest["accepted"] == summary.accepted
    assert len(manifest["instances"]) == summary.accepted

    for entry in manifest["instances"]:
        scenario_file = tmp_path / f"{entry['scenario_id']}.json"
        assert scenario_file.exists()
        Scenario(**json.loads(scenario_file.read_text(encoding="utf-8")))  # round-trips


def test_generate_holdouts_is_deterministic_given_the_same_seed(tmp_path):
    a = generate_holdouts(private_seed=555, n_per_template=2, output_dir=tmp_path / "a")
    b = generate_holdouts(private_seed=555, n_per_template=2, output_dir=tmp_path / "b")
    assert a.accepted == b.accepted
    assert a.candidates_generated == b.candidates_generated


def test_generated_holdout_output_directory_is_gitignored():
    """docs/benchmark/PUBLIC_PRIVATE_POLICY.md's whole point fails silently if this ever
    stops being true — a regression here means holdout_private/ could enter git history."""
    from pathlib import Path
    import subprocess

    repo_root = Path(holdouts.__file__).resolve().parent.parent.parent
    result = subprocess.run(
        ["git", "check-ignore", "-q", "holdouts_private/probe.json"],
        cwd=repo_root,
        timeout=5,
    )
    assert result.returncode == 0, "holdouts_private/ is not git-ignored — check .gitignore"
