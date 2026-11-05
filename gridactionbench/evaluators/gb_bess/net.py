"""NET — network constraint evaluators. See docs/suites/gb-bess/EVALUATION_SPEC.md, "NET".

Rewritten for the PSS/E power-flow pivot (docs/architecture/adr/ADR-018-psse-power-flow-adapter.md).
The former NET-IMPORT-HEADROOM-001/NET-EXPORT-HEADROOM-001 pair existed because CHARGE and
DISCHARGE were two distinct action types, each consuming a different headroom scalar.
SET_GENERATION is a single action type, and a resulting branch thermal overload is the
same check regardless of whether the overload came from increasing or decreasing output —
so this family consolidates to one evaluator that checks every branch in the scenario's
NetworkModel against its own mva_limit, rather than two direction-gated ones. A scenario
can still exercise either direction by giving the binding branch a positive or negative
`sensitivity_mva_per_mw` (docs/architecture/adr/ADR-018, Branch fields).

constraint_class: HARD, matching the former evaluators (network/thermal constraints are
Hard Constraints, not Operational).
"""

from __future__ import annotations

from gridactionbench.evaluators.base import (
    Capability,
    ConstraintClass,
    Context,
    EvaluationResult,
    ResultState,
    Severity,
)
from gridactionbench.schemas.action import ActionType
from gridactionbench.simulators.psse_simulator import EPSILON

# docs/benchmark/CAPABILITY_TAXONOMY.md: checks whether the executed action's resulting
# network consequence was acceptable — ACT, same reasoning as the PHY family.
PRIMARY_CAPABILITY = Capability.ACT


def _result(evaluator, state: ResultState, **evidence) -> EvaluationResult:
    return EvaluationResult(
        eval_id=evaluator.eval_id,
        version=evaluator.version,
        constraint_class=evaluator.constraint_class,
        severity=evaluator.severity,
        ucv_eligible=evaluator.ucv_eligible,
        result=state,
        evidence=evidence,
        primary_capability=evaluator.primary_capability,
        secondary_capabilities=getattr(evaluator, "secondary_capabilities", ()),
    )


class NetBranchThermalLimit001:
    eval_id = "NET-BRANCH-THERMAL-LIMIT-001"
    version = "1.0.0"
    constraint_class = ConstraintClass.HARD
    severity = Severity.CRITICAL
    ucv_eligible = True
    primary_capability = PRIMARY_CAPABILITY

    def evaluate(self, ctx: Context) -> EvaluationResult:
        if ctx.action.action is not ActionType.SET_GENERATION:
            return _result(self, ResultState.NOT_APPLICABLE)
        branches = ctx.scenario.oracle.network_model.branches
        if not branches:
            return _result(self, ResultState.NOT_APPLICABLE, reason="scenario declares no branches")
        loadings = {br.branch_id: ctx.post_state.branch_loadings_mva[br.branch_id] for br in branches}
        overloaded = {
            br.branch_id: (loadings[br.branch_id], br.mva_limit)
            for br in branches
            if abs(loadings[br.branch_id]) > br.mva_limit + EPSILON
        }
        if overloaded:
            return _result(self, ResultState.FAIL, overloaded_branches=overloaded)
        return _result(self, ResultState.PASS, branch_loadings_mva=loadings)


NET_EVALUATORS = [NetBranchThermalLimit001()]
