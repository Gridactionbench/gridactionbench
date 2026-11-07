"""Acceptance criteria for a generated GB-BESS scenario instance to be usable as an
official private holdout — docs/benchmark/PUBLIC_PRIVATE_POLICY.md, item 4, adapted from
the Trashchenkov "Power Systems Agent Benchmark" pattern (docs/research/PRIOR_ART.md §1.1,
item 3):

1. The reference agent (`RuleBasedAgent`) must produce a scoreable, non-degenerate
   outcome — no error, a schema-valid action, and (for a power-bearing action) a real
   simulator post-state.
2. The instance's ground truth must be internally consistent — a fully compliant
   reference agent must never be forced into a HARD-constraint-invalid action. If it is,
   the scenario's Oracle values are self-contradictory (e.g. the exact case the policy
   names: "a scenario's oracle values must not make every action simultaneously invalid,
   unless that is the specific point of the scenario, e.g. HUM-019" — GB-BESS-HUM-019-style
   escalation-required scenarios are unaffected by this check, since ESCALATE never fails a
   HARD-class evaluator by construction, gridactionbench/core/validator.py).
3. A basic sensitivity check: does a small (2%) perturbation of the reference price flip
   the reference agent's chosen action *type*? Reported as a diagnostic flag, never used to
   auto-reject an instance — some templates are deliberately boundary-precision probes
   where such a flip is the intended behaviour, not a defect (docs/benchmark/
   PUBLIC_PRIVATE_POLICY.md's own "a basic sensitivity check, not a formal proof" caveat).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from baselines.rule_based.agent import RuleBasedAgent
from gridactionbench.agents.base import AgentAdapter
from gridactionbench.core.decision_record import DecisionRecord
from gridactionbench.core.scenario import Scenario
from gridactionbench.runners.single_step import run_single_step
from gridactionbench.schemas.action import ActionType

DT_HOURS = 0.5
PRICE_PERTURBATION_FRACTION = 0.02
# A purely multiplicative perturbation (price * (1 + fraction)) can never cross zero — it
# preserves sign for any nonzero price — so it would never catch the single most relevant
# boundary for RuleBasedAgent's action choice (the price=0 increase/decrease crossover).
# This floor makes the perturbation additive and large enough, in absolute terms, to
# actually test near-zero prices, not just scale large ones.
MIN_ABSOLUTE_PRICE_PERTURBATION_GBP = 1.0


@dataclass
class AcceptanceResult:
    scenario_id: str
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    sensitivity_flagged: bool = False


def check_acceptance(
    scenario: Scenario,
    dt_hours: float = DT_HOURS,
    agent: AgentAdapter | None = None,
) -> AcceptanceResult:
    agent = agent or RuleBasedAgent(dt_hours=dt_hours)
    record = run_single_step(scenario, agent, dt_hours)
    reasons = _check_reasons(record)
    sensitivity_flagged = _is_sensitive_to_small_perturbation(scenario, agent, record, dt_hours)
    return AcceptanceResult(
        scenario_id=scenario.scenario_id,
        accepted=not reasons,
        reasons=reasons,
        sensitivity_flagged=sensitivity_flagged,
    )


def _check_reasons(record: DecisionRecord) -> list[str]:
    reasons: list[str] = []
    if record.errors:
        reasons.append(f"reference agent errored: {record.errors}")
    if not record.schema_valid:
        reasons.append("reference agent produced a schema-invalid action")
    if (
        record.parsed_action is not None
        and record.parsed_action.action is ActionType.SET_GENERATION
        and record.simulator_post_state is None
    ):
        reasons.append("reference agent's power-bearing action produced no simulator post-state")
    if record.hard_constraint_valid is False:
        reasons.append(
            "reference agent's own chosen action failed a HARD-class evaluator — "
            "oracle values are likely self-contradictory"
        )
    return reasons


def _is_sensitive_to_small_perturbation(
    scenario: Scenario, agent: AgentAdapter, record: DecisionRecord, dt_hours: float
) -> bool:
    price = scenario.oracle.market.reference_price_gbp_mwh
    if price is None or record.parsed_action is None:
        return False
    delta = max(abs(price) * PRICE_PERTURBATION_FRACTION, MIN_ABSOLUTE_PRICE_PERTURBATION_GBP)
    # Compares the full parsed action, not just `.action` — SET_GENERATION covers both the
    # former CHARGE and DISCHARGE directions (docs/architecture/adr/ADR-018), so a
    # same-type action whose `mw` flips from an increase to a decrease across the price=0
    # crossover is exactly the sensitivity this check exists to catch, and `.action` alone
    # would no longer distinguish it.
    reference = record.parsed_action.model_dump()
    for perturbed_price in (price + delta, price - delta):
        perturbed = scenario.model_copy(deep=True)
        perturbed.oracle.market.reference_price_gbp_mwh = perturbed_price
        perturbed_record = run_single_step(perturbed, agent, dt_hours)
        perturbed_action = perturbed_record.parsed_action.model_dump() if perturbed_record.parsed_action else None
        if reference != perturbed_action:
            return True
    return False
