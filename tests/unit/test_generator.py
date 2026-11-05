"""Tests for the parameterised scenario generator (gridactionbench/scenarios/generator.py).

See docs/suites/gb-bess/SCENARIO_TEMPLATES.md for what this generator is (and is not) —
these tests check the generator's own mechanical correctness (determinism, uniqueness,
schema validity), not calibration outcomes (those live in tests/golden/).
"""

from __future__ import annotations

from gridactionbench.scenarios.generator import TEMPLATES, coverage_report, generate


def test_generate_is_deterministic_given_the_same_seed():
    a = generate(n_per_template=5, seed=7)
    b = generate(n_per_template=5, seed=7)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]


def test_generate_produces_different_scenarios_for_different_seeds():
    a = generate(n_per_template=5, seed=1)
    b = generate(n_per_template=5, seed=2)
    assert [s.model_dump() for s in a] != [s.model_dump() for s in b]


def test_every_generated_scenario_has_a_unique_id():
    scenarios = generate(n_per_template=15, seed=42)
    ids = [s.scenario_id for s in scenarios]
    assert len(ids) == len(set(ids))


def test_generated_scenario_count_matches_templates_times_n():
    n_per_template = 10
    scenarios = generate(n_per_template=n_per_template, seed=1)
    assert len(scenarios) == len(TEMPLATES) * n_per_template


def test_all_seven_families_are_represented_in_the_templates():
    families = {t.family for t in TEMPLATES}
    assert families == {"PHY", "NET", "OPS", "DATA", "MKT", "ADV", "HUM"}


def test_coverage_report_covers_every_declared_dimension():
    report = coverage_report()
    for template in TEMPLATES:
        for dimension in template.coverage:
            assert dimension in report
            assert sum(report[dimension].values()) == len(TEMPLATES)


def test_adding_a_template_does_not_change_another_templates_generated_instances():
    """Reproducibility guarantee stated in the generator's own docstring: each template is
    seeded from (seed, template_id), so the template list's composition doesn't leak into
    another template's random draws."""
    full = {s.scenario_id: s.model_dump() for s in generate(TEMPLATES, n_per_template=3, seed=42)}
    subset = generate(TEMPLATES[:5], n_per_template=3, seed=42)
    for s in subset:
        assert full[s.scenario_id] == s.model_dump()


def test_mkt_templates_declare_preferred_actions_matching_their_own_price_sign():
    """docs/benchmark/SPECIFICATION.md §4 / gridactionbench/evaluators/gb_bess/mkt.py.
    Every generated MKT-NEUTRAL/MKT-VOLATILITY instance's preferred_actions must match
    whether that instance's own declared price gives any incentive to act at all.
    Direction-specific preference (the pre-pivot CHARGE-at-negative/DISCHARGE-at-positive
    check) is no longer possible — see generator.py's `_price_preferred_action` docstring
    and the module docstring here: SET_GENERATION covers both directions now, so this
    evaluator can only test "acted vs not," not which way."""
    mkt_templates = [t for t in TEMPLATES if t.family == "MKT"]
    assert mkt_templates, "expected at least one MKT template"
    for scenario in generate(templates=mkt_templates, n_per_template=20, seed=7):
        price = scenario.oracle.market.reference_price_gbp_mwh
        if price != 0:
            assert scenario.preferred_actions == ["SET_GENERATION"], scenario.scenario_id
        else:
            assert scenario.preferred_actions == [], scenario.scenario_id


def test_rule_based_agent_never_fails_mkt_preferred_action_across_generated_mkt_instances():
    """The design-critical invariant this evaluator depends on: RuleBasedAgent acts on
    price sign alone (baselines/rule_based/agent.py), matching exactly how MKT templates
    declare preferred_actions — so it must never fail this check, the same way it never
    fails any other evaluator (docs/benchmark/CALIBRATION_RESULTS.md)."""
    from baselines.rule_based.agent import RuleBasedAgent
    from gridactionbench.runners.single_step import run_single_step

    mkt_templates = [t for t in TEMPLATES if t.family == "MKT"]
    agent = RuleBasedAgent(dt_hours=0.5)
    for scenario in generate(templates=mkt_templates, n_per_template=20, seed=7):
        record = run_single_step(scenario, agent, 0.5)
        mkt_results = [r for r in record.evaluation_results if r["eval_id"] == "MKT-PREFERRED-ACTION-001"]
        assert mkt_results, scenario.scenario_id
        assert mkt_results[0]["result"] != "FAIL", scenario.scenario_id


def test_always_idle_agent_fails_mkt_preferred_action_on_a_nonzero_price_instance():
    """Demonstration case proving MKT-PREFERRED-ACTION-001 has real discriminative power,
    not just a mechanism that never fires — AlwaysIdleAgent never charges/discharges
    regardless of price (baselines/always_idle/agent.py)."""
    from baselines.always_idle.agent import AlwaysIdleAgent
    from gridactionbench.runners.single_step import run_single_step

    mkt_templates = [t for t in TEMPLATES if t.family == "MKT"]
    agent = AlwaysIdleAgent()
    scenarios = [s for s in generate(templates=mkt_templates, n_per_template=20, seed=7) if s.preferred_actions]
    assert scenarios, "expected at least one MKT instance with a nonzero price"
    record = run_single_step(scenarios[0], agent, 0.5)
    mkt_result = next(r for r in record.evaluation_results if r["eval_id"] == "MKT-PREFERRED-ACTION-001")
    assert mkt_result["result"] == "FAIL"
    assert mkt_result["ucv_eligible"] is False
    assert record.ucv is False  # decision-quality only — never a UCV
