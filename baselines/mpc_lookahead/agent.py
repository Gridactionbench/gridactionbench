"""MpcLookaheadAgent — reference agent (added 2026-09-09).

Mirrors RuleBasedAgent's escalation/constraint-respecting logic and boundary-power
computation exactly (baselines/rule_based/agent.py), with one inserted branch before the
greedy fallback: if `market.price_forecast_gbp_mwh` signals a same-direction opportunity
at least `LOOKAHEAD_THRESHOLD` times better than the current price, hold (IDLE) now rather
than lock in the lesser price, reserving capacity for the forecast opportunity.

Rewritten for the PSS/E power-flow pivot (docs/architecture/adr/ADR-018-psse-power-flow-adapter.md)
— see RuleBasedAgent's module docstring for what changed and why; this agent's own
lookahead logic is otherwise unchanged.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1, ReasonCode
from gridactionbench.schemas.observation import EnergyObservationV1

# The forecast opportunity must be at least this many times better than the current price
# to justify holding back now — a deliberately simple, fixed threshold, not a calibrated
# constant (same "illustrative, not validated" status as RuleBasedAgent's own thresholds,
# docs/project/ASSUMPTIONS.md).
LOOKAHEAD_THRESHOLD = 2.0

EPSILON = 1e-6


class MpcLookaheadAgent:
    agent_id = "mpc-lookahead"
    agent_version = "0.2.0"
    agent_type = "optimisation"

    def __init__(self, dt_hours: float):
        self.dt_hours = dt_hours

    def act(self, observation: EnergyObservationV1) -> AgentActionV1:
        escalation = self._check_information_sufficiency(observation)
        if escalation is not None:
            return escalation

        if not observation.network_model.generators:
            return AgentActionV1(action=ActionType.IDLE)
        gen = observation.network_model.generators[0]
        policy = observation.operational_policy
        price = observation.market.reference_price_gbp_mwh
        forecast = observation.market.price_forecast_gbp_mwh

        if price is not None and forecast is not None:
            if price > 0 and forecast > price * LOOKAHEAD_THRESHOLD:
                # A significantly better increase-generation opportunity is forecast —
                # hold back now rather than lock in the lesser price.
                return AgentActionV1(action=ActionType.IDLE)
            if price < 0 and forecast < price * LOOKAHEAD_THRESHOLD:
                # Mirror for decreasing generation: a significantly better (more
                # negative) opportunity is forecast.
                return AgentActionV1(action=ActionType.IDLE)

        if price is not None and price > 0 and not policy.temporary_limits.generation_increase_prohibited:
            increase = self._max_increase_mw(observation)
            if increase > EPSILON:
                return AgentActionV1(action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output + increase)

        if price is not None and price < 0 and not policy.temporary_limits.generation_decrease_prohibited:
            decrease = self._max_decrease_mw(observation)
            if decrease > EPSILON:
                return AgentActionV1(action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output - decrease)

        return AgentActionV1(action=ActionType.IDLE)

    def _check_information_sufficiency(self, observation: EnergyObservationV1) -> AgentActionV1 | None:
        telem = observation.telemetry
        if telem.field_status.voltage == "missing":
            return AgentActionV1(action=ActionType.ESCALATE, reason_code=ReasonCode.MISSING_CRITICAL_DATA)
        if telem.field_status.voltage == "stale":
            return AgentActionV1(action=ActionType.ESCALATE, reason_code=ReasonCode.STALE_CRITICAL_DATA)
        if telem.field_status.voltage == "conflicting":
            return AgentActionV1(action=ActionType.ESCALATE, reason_code=ReasonCode.TELEMETRY_CONFLICT)
        if telem.field_status.branch_flow == "missing":
            return AgentActionV1(action=ActionType.ESCALATE, reason_code=ReasonCode.MISSING_CRITICAL_DATA)
        if any("implausible" in flag for flag in telem.quality_flags):
            return AgentActionV1(action=ActionType.ESCALATE, reason_code=ReasonCode.IMPLAUSIBLE_TELEMETRY)
        if observation.operational_policy.approval_required:
            return AgentActionV1(action=ActionType.ESCALATE, reason_code=ReasonCode.APPROVAL_REQUIRED)
        if observation.injected_field:
            return AgentActionV1(action=ActionType.ESCALATE, reason_code=ReasonCode.SUSPECTED_ADVERSARIAL_INPUT)
        return None

    def _max_increase_mw(self, observation: EnergyObservationV1) -> float:
        gen = observation.network_model.generators[0]
        policy = observation.operational_policy
        ceiling = gen.mw_max
        if policy.temporary_limits.max_mw_override is not None:
            ceiling = min(ceiling, policy.temporary_limits.max_mw_override)
        candidates = [ceiling - gen.mw_output, gen.mw_ramp_up_limit_per_step]
        for bus in observation.network_model.buses:
            if bus.bus_id == gen.bus_id and gen.voltage_sensitivity_pu_per_mw > 0:
                candidates.append((bus.voltage_max_pu - bus.voltage_pu) / gen.voltage_sensitivity_pu_per_mw)
        for branch in observation.network_model.branches:
            if branch.sensitivity_mva_per_mw > 0:
                candidates.append((branch.mva_limit - branch.mva_flow) / branch.sensitivity_mva_per_mw)
        return max(0.0, min(candidates))

    def _max_decrease_mw(self, observation: EnergyObservationV1) -> float:
        gen = observation.network_model.generators[0]
        policy = observation.operational_policy
        floor = max(gen.mw_min, policy.reserve_mw_margin or gen.mw_min)
        candidates = [gen.mw_output - floor, gen.mw_ramp_down_limit_per_step]
        for bus in observation.network_model.buses:
            if bus.bus_id == gen.bus_id and gen.voltage_sensitivity_pu_per_mw > 0:
                candidates.append((bus.voltage_pu - bus.voltage_min_pu) / gen.voltage_sensitivity_pu_per_mw)
        for branch in observation.network_model.branches:
            if branch.sensitivity_mva_per_mw < 0:
                candidates.append((branch.mva_limit - branch.mva_flow) / -branch.sensitivity_mva_per_mw)
        return max(0.0, min(candidates))
