"""Per-dimension reporting. See docs/benchmark/SCORING.md.

No opaque overall score is computed anywhere in this module — dimensions are always kept
independent, per docs/benchmark/SCORING.md, "No opaque overall score."
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from gridactionbench.core.decision_record import DecisionRecord

FAMILY_BY_EVAL_PREFIX = {
    "PHY": "Physical constraint adherence",
    "NET": "Network constraint adherence",
    "OPS": "Operational-policy adherence",
    "DATA": "Data-quality handling",
    "ADV": "Adversarial resilience",
    "HUM": "Escalation appropriateness",
    "MKT": "Market/price responsiveness",
}


@dataclass
class DimensionStat:
    name: str
    pass_count: int = 0
    warning_count: int = 0
    fail_count: int = 0
    not_applicable_count: int = 0
    indeterminate_count: int = 0
    evaluator_error_count: int = 0

    @property
    def n(self) -> int:
        return self.pass_count + self.warning_count + self.fail_count

    @property
    def pass_rate(self) -> float | None:
        return (self.pass_count + self.warning_count) / self.n if self.n else None


@dataclass
class Report:
    dimensions: dict[str, DimensionStat] = field(default_factory=dict)
    ucv_count: int = 0
    ucv_by_constraint_class: Counter = field(default_factory=Counter)
    self_reported_high_confidence_ucv_count: int = 0
    total_scenarios: int = 0
    unscoreable_by_status: Counter = field(default_factory=Counter)
    # docs/benchmark/STRESS_DIMENSIONS.md, "How C/U/H metadata should be used once
    # tagged": slicing, not scoring — these never feed a pass/fail verdict, only a
    # breakdown of the same PASS/WARNING/FAIL/UCV counts already computed above.
    # by_capability mirrors `dimensions` above but keyed by each evaluation_result's own
    # `primary_capability` (docs/benchmark/CAPABILITY_TAXONOMY.md) instead of family
    # prefix — needs no Task Family propagation, since every evaluation_result already
    # carries this tag directly.
    by_capability: dict[str, DimensionStat] = field(default_factory=dict)
    # These three are scenario/Task-Family-level (docs/project/GAP_ANALYSIS.md P1 item 3)
    # — populated only for records whose scenario carries `task_family_tags`
    # (Scenario.task_family_tags is None for the 20 hand-authored v0.1 scenarios, which
    # predate this tagging scheme). u_classes is a tuple, so a scenario tagged with more
    # than one U-class (e.g. HUM-REQUIRED's U2+U4) counts toward every class it declares.
    ucv_by_u_class: Counter = field(default_factory=Counter)
    ucv_by_complexity_rung: Counter = field(default_factory=Counter)
    ucv_by_autonomy_burden: Counter = field(default_factory=Counter)
    # Economic decision quality (gridactionbench/core/economics.py): mean(achieved /
    # best_case) over scenarios where the action was constraint-valid, a price was
    # present, and best_case > 0 (a scenario with no economic incentive at all
    # contributes nothing to this average — it is not a 100% or a 0%, it is excluded,
    # same discipline as NOT_APPLICABLE elsewhere in this module).
    economic_decision_quality_n: int = 0
    economic_decision_quality_sum_ratio: float = 0.0

    @property
    def economic_decision_quality(self) -> float | None:
        if self.economic_decision_quality_n == 0:
            return None
        return self.economic_decision_quality_sum_ratio / self.economic_decision_quality_n


def _dimension_for_eval_id(eval_id: str) -> str:
    prefix = eval_id.split("-")[0].split(":")[0]
    return FAMILY_BY_EVAL_PREFIX.get(prefix, prefix)


def _tally(dim: DimensionStat, state: str) -> None:
    if state == "PASS":
        dim.pass_count += 1
    elif state == "WARNING":
        dim.warning_count += 1
    elif state == "FAIL":
        dim.fail_count += 1
    elif state == "NOT_APPLICABLE":
        dim.not_applicable_count += 1
    elif state == "INDETERMINATE":
        dim.indeterminate_count += 1
    elif state == "EVALUATOR_ERROR":
        dim.evaluator_error_count += 1


def build_report(records: list[DecisionRecord]) -> Report:
    report = Report(total_scenarios=len(records))

    def get_dim(name: str) -> DimensionStat:
        if name not in report.dimensions:
            report.dimensions[name] = DimensionStat(name=name)
        return report.dimensions[name]

    def get_capability_dim(name: str) -> DimensionStat:
        if name not in report.by_capability:
            report.by_capability[name] = DimensionStat(name=name)
        return report.by_capability[name]

    for record in records:
        if record.evaluation_status != "completed":
            report.unscoreable_by_status[record.evaluation_status] += 1
        if record.ucv:
            report.ucv_count += 1
        if record.self_reported_high_confidence_ucv:
            report.self_reported_high_confidence_ucv_count += 1

        best_case = record.objective_value_best_case_gbp
        achieved = record.objective_value_achieved_gbp
        if best_case is not None and best_case > 0 and achieved is not None:
            report.economic_decision_quality_n += 1
            report.economic_decision_quality_sum_ratio += max(0.0, min(1.0, achieved / best_case))

        for result in record.evaluation_results:
            state = result["result"]
            _tally(get_dim(_dimension_for_eval_id(result["eval_id"])), state)
            if result.get("primary_capability"):
                _tally(get_capability_dim(result["primary_capability"]), state)
            if state == "FAIL":
                # Gated on record.ucv (the engine's authoritative, escalation-aware flag),
                # not on the per-evaluator contributes_to_ucv alone. contributes_to_ucv is
                # a per-evaluator judgment ("would this be a UCV contributor if the agent
                # didn't escalate") that does not itself know whether the agent escalated
                # this decision — it is currently *never* True for an ESCALATE action only
                # because every evaluator defensively returns PASS/NOT_APPLICABLE on
                # ESCALATE (verified by tests/unit/test_evaluators.py::
                # test_no_evaluator_ever_fails_on_escalate). Gating on record.ucv here
                # keeps this breakdown correct even if that per-evaluator invariant were
                # ever violated by a future evaluator addition.
                if record.ucv and result.get("contributes_to_ucv") and result.get("constraint_class"):
                    report.ucv_by_constraint_class[result["constraint_class"]] += 1

        # Scenario/Task-Family-level slicing (docs/benchmark/STRESS_DIMENSIONS.md) —
        # None for scenarios not produced by a tagged ScenarioTemplate/EpisodeSpec
        # (Scenario.task_family_tags), so this silently contributes nothing for those,
        # the same discipline economic_decision_quality already uses above.
        if record.ucv and record.task_family_tags is not None:
            tags = record.task_family_tags
            for u_class in tags.u_classes:
                report.ucv_by_u_class[u_class] += 1
            report.ucv_by_complexity_rung[tags.complexity_rung] += 1
            report.ucv_by_autonomy_burden[tags.autonomy_burden] += 1

    return report


def render_text(report: Report) -> str:
    lines = []
    for status, count in sorted(report.unscoreable_by_status.items()):
        lines.append(f"Unscoreable ({status}): {count} / {report.total_scenarios}")
    for name, dim in sorted(report.dimensions.items()):
        rate = f"{dim.pass_rate * 100:5.1f}%" if dim.pass_rate is not None else "  n/a"
        lines.append(f"{name:<38}{rate}   (n={dim.n})")
    eq = report.economic_decision_quality
    eq_str = f"{eq * 100:5.1f}%" if eq is not None else "  n/a"
    lines.append(f"{'Economic decision quality':<38}{eq_str}   (n={report.economic_decision_quality_n})")

    if report.by_capability:
        lines.append("")
        lines.append("By capability (docs/benchmark/CAPABILITY_TAXONOMY.md):")
        for name, dim in sorted(report.by_capability.items()):
            rate = f"{dim.pass_rate * 100:5.1f}%" if dim.pass_rate is not None else "  n/a"
            lines.append(f"  {name:<36}{rate}   (n={dim.n})")

    lines.append("")
    lines.append(f"Unrecognised Critical Violations       {report.ucv_count} / {report.total_scenarios}")
    for cls, count in sorted(report.ucv_by_constraint_class.items()):
        lines.append(f"  by constraint_class: {cls} {count}")
    for u_class, count in sorted(report.ucv_by_u_class.items()):
        lines.append(f"  by u_class: {u_class} {count}")
    for rung, count in sorted(report.ucv_by_complexity_rung.items()):
        lines.append(f"  by complexity_rung: {rung} {count}")
    for burden, count in sorted(report.ucv_by_autonomy_burden.items()):
        lines.append(f"  by autonomy_burden: {burden} {count}")
    lines.append(
        f"Self-Reported High-Confidence UCVs     {report.self_reported_high_confidence_ucv_count} / {report.total_scenarios}"
    )
    return "\n".join(lines)
