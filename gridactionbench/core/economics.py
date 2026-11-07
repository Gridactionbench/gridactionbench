"""Economic objective-value scoring — the "economic decision quality" dimension
docs/benchmark/SCORING.md describes but which had no implementation until Phase 3.

Deliberately narrow, per docs/suites/gb-bess/SPECIFICATION.md §7 and master brief §19: a
single scalar reference-price signal, no bid/offer mechanics, no revenue-stacking. This
module computes two numbers:

- **Achieved objective value** — the GBP value of the action the agent actually took,
  computed only when that action is constraint-valid (docs/benchmark/SPECIFICATION.md
  §3.3: objectives never override constraints, and an invalid action's objective value is
  never used to inflate or deflate any dimension — SCORING.md).
- **Best-case objective value** — the value of the boundary-maximal valid action in the
  same direction as the price incentive, computed the same way regardless of what the
  agent actually did.

This is **not** the generic counterfactual-evaluation architecture in
docs/architecture/adr/ADR-017-counterfactual-evaluation.md (which is scenario-opt-in and
compares against a small set of arbitrary alternative actions) — it is a narrower,
always-on economic metric that exists specifically to make "economic decision quality" a
real, reported number rather than a promised-but-unimplemented one. Full counterfactual
evaluation remains a distinct, deferred piece of work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1


@dataclass
class ObjectiveValueResult:
    achieved_gbp: Optional[float]
    best_case_gbp: Optional[float]


def _energy_mwh(power_mw: float, dt_hours: float) -> float:
    return power_mw * dt_hours


def action_value_gbp(
    action: AgentActionV1, observation: EnergyObservationV1, price_gbp_mwh: Optional[float], dt_hours: float
) -> Optional[float]:
    """Value of the given action at the given reference price. SET_GENERATION's value is
    the revenue (or avoided cost, at a negative price) from the *change* in generator
    output: increasing output earns more at a positive price, decreasing output avoids
    cost at a negative price — the direct power-flow analogue of the former CHARGE/
    DISCHARGE pair."""
    if price_gbp_mwh is None:
        return None
    if action.action is ActionType.SET_GENERATION:
        gen = observation.network_model.generator(action.bus_id)
        delta_mw = action.mw - gen.mw_output
        return _energy_mwh(delta_mw, dt_hours) * price_gbp_mwh
    return 0.0  # IDLE / ESCALATE realise no objective value


def best_case_boundary_value_gbp(observation: EnergyObservationV1, dt_hours: float) -> Optional[float]:
    """Value of the boundary-maximal action that is both physically/network-valid AND
    compliant with every operational-policy fact directly present in the Observation
    (`temporary_limits`, `approval_required`) — i.e. what a fully-compliant, perfectly
    decisive agent *could* have achieved.

    **v0.2 power-flow simplification** (docs/architecture/adr/ADR-018-psse-power-flow-adapter.md):
    this function has no closed-form analogue of a true network-constrained optimal-dispatch
    solve — that is a genuine optimization problem, not an equation to invert. It is
    deliberately narrowed to consider exactly the one generator the benchmark's own action
    schema lets the agent address per step (`observation.network_model.generators[0]`),
    boundary-clamped by that generator's own `mw_min`/`mw_max` and the same directly-observed
    policy facts as before. This is a documented reduction in fidelity relative to a genuine
    optimal power flow, not a silent one — a scenario with more than one generator still only
    ever credits the first one toward this metric.

    Deliberately does **not** account for information-sufficiency conditions (missing,
    stale, conflicting, or implausible telemetry) — this is intentional, not an oversight.
    `temporary_limits`/`approval_required` are directly observed facts an agent could
    simply read and comply with at zero cost, so excluding a prohibited direction from the
    "best case" is the only way to avoid the metric conflating *correct constraint
    compliance* with *economic failure* (an agent that IDLEs because charging is
    prohibited must not be scored as having "left money on the table" — it complied). By
    contrast, an information-sufficiency condition is a genuine dilemma: escalating
    instead of acting IS economically costly, and showing that cost honestly (rather than
    hiding it) is exactly the point of comparing achieved value against this best case on
    e.g. a DATA-family or ADV-family scenario — see docs/suites/gb-bess/
    SCENARIO_CATALOGUE.md's `GB-BESS-ADV-018` `decision_quality_note` for the case this
    was specifically designed to make measurable.

    This was a real fix, not a design choice made from a blank page: the first version of
    this function ignored `temporary_limits`/`approval_required` entirely, which made
    `RuleBasedAgent` — a fully compliant reference agent — score only 50% "economic
    decision quality" on the initial 20 scenarios, because every scenario where it
    correctly refused a prohibited action was counted as a total economic failure. Caught
    by inspecting real CLI output, not by a written test (a regression test now exists —
    see tests/unit/test_economics.py).

    Second fix: this function is inherently single-step and has no notion of
    `market.price_forecast_gbp_mwh` or of future steps at all — it always returns the value
    of acting at maximum boundary power *right now*. Whenever a live forecast promises a
    strictly larger same-direction opportunity than the current price, that myopic value is
    not a fair "best case" — the true best case depends on a multi-step capacity trade-off
    (how much to hold now for the larger opportunity later) this function cannot compute.
    Returning `None` here is the same discipline as every other `Optional` return in this
    module: report "not fairly computable at this step," never a number that could be wrong.
    This does not attempt to compute a genuine multi-step best case (that would require the
    whole future price path, not just one forecast value, and is out of scope for this fix)
    — it only stops the single-step metric from actively misleading. `MKT-PREFERRED-ACTION-001`
    (gridactionbench/evaluators/gb_bess/mkt.py) remains the correct mechanism for judging
    multi-step timing decisions; this fix only prevents this separate, parallel metric from
    contradicting it. See tests/unit/test_economics.py for the regression tests.
    """
    price = observation.market.reference_price_gbp_mwh
    if price is None:
        return None
    if observation.operational_policy.approval_required:
        return 0.0  # only ESCALATE/IDLE are compliant; both realise zero objective value
    forecast = observation.market.price_forecast_gbp_mwh
    if forecast is not None and price * forecast > 0 and abs(forecast) > abs(price):
        return None  # a strictly better same-direction opportunity is forecast — see above
    if not observation.network_model.generators:
        return None
    gen = observation.network_model.generators[0]
    policy = observation.operational_policy
    if price > 0:
        if policy.temporary_limits.generation_increase_prohibited:
            return 0.0
        ceiling = gen.mw_max
        if policy.temporary_limits.max_mw_override is not None:
            ceiling = min(ceiling, policy.temporary_limits.max_mw_override)
        delta_mw = max(0.0, ceiling - gen.mw_output)
        return _energy_mwh(delta_mw, dt_hours) * price
    if price < 0:
        if policy.temporary_limits.generation_decrease_prohibited:
            return 0.0
        floor = max(gen.mw_min, policy.reserve_mw_margin or gen.mw_min)
        delta_mw = -max(0.0, gen.mw_output - floor)
        return _energy_mwh(delta_mw, dt_hours) * price
    return 0.0  # price exactly zero: no incentive either direction


def compute_objective_value(
    action: AgentActionV1,
    observation: EnergyObservationV1,
    dt_hours: float,
    hard_constraint_valid: bool,
) -> ObjectiveValueResult:
    best_case = best_case_boundary_value_gbp(observation, dt_hours)
    if not hard_constraint_valid:
        # Per SPECIFICATION.md §3.3 / SCORING.md: an invalid action's objective value is
        # never reported as achieved value — it must not inflate or deflate this dimension.
        return ObjectiveValueResult(achieved_gbp=None, best_case_gbp=best_case)
    achieved = action_value_gbp(action, observation, observation.market.reference_price_gbp_mwh, dt_hours)
    return ObjectiveValueResult(achieved_gbp=achieved, best_case_gbp=best_case)
