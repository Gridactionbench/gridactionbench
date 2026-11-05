"""RuleBasedAgent — transparent deterministic controller. See master brief §26.

Policy, in priority order:
1. Escalate on any recognised information-sufficiency red flag (missing/stale/conflicting
   voltage telemetry, missing branch-loading telemetry, an implausible quality flag, an
   approval requirement, or the presence of an adversarial injected_field).
2. Otherwise, increase this scenario's one controllable generator's output at the
   boundary-maximal safe value when price is positive and increase is not prohibited;
   decrease at the boundary-maximal safe value when price is negative and decrease is not
   prohibited.
3. Otherwise, idle.

Rewritten for the PSS/E power-flow pivot (docs/architecture/adr/ADR-018-psse-power-flow-adapter.md):
boundary-maximal MW is now computed from the generator's own nameplate/ramp limits plus
the linear voltage/branch-loading sensitivities the Oracle declares (NetworkModel's
`voltage_sensitivity_pu_per_mw`/`sensitivity_mva_per_mw`) — the same "offline-study-derived
headroom" an agent would be given in a real flexible/ANM connection agreement, letting it
reason about voltage/thermal consequences without running its own power-flow solve. This
agent needs its own dt_hours for interface symmetry with the prior model, though v0.2's
single-solve step does not itself integrate over time.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1, ReasonCode
from gridactionbench.schemas.observation import EnergyObservationV1

# Floating-point tolerance for "is this actually a change," matching
# gridactionbench.simulators.psse_simulator.EPSILON.
EPSILON = 1e-6


class RuleBasedAgent:
    agent_id = "rule-based"
    agent_version = "0.2.0"
    agent_type = "rule_based"

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
