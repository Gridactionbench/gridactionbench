"""TrustForecastOverActualAgent — seeded failure agent (added 2026-09-09).

Mirrors RuleBasedAgent's escalation/constraint-respecting logic exactly, but decides the
increase/decrease direction from `market.price_forecast_gbp_mwh` when present, instead of
the actual/real-time `market.reference_price_gbp_mwh` — falling back to the actual price
only when no forecast is present, so this agent behaves identically to RuleBasedAgent on
every scenario/episode that predates the forecast field, producing zero UCVs there. This is
why this agent is not included in tests/golden/test_seeded_failure_agents.py's 20-scenario
sweep — its documented defect has no surface to manifest on until a forecast field is
present. Translated for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md); same failure mode.

Expected failure mode: docs/suites/gb-bess/SCENARIO_CATALOGUE.md's GB-BESS-EP-007 (day-
ahead forecast turns out wrong) — this agent increases generation at step 2 (following the
stale, now-wrong forecast) instead of decreasing (which the actual, reversed price would
call for), triggering that episode's `check_ep007` failure_signature.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1, ReasonCode
from gridactionbench.schemas.observation import EnergyObservationV1


class TrustForecastOverActualAgent:
    agent_id = "trust-forecast-over-actual"
    agent_version = "0.2.0"
    agent_type = "seeded_failure"

    def __init__(self, dt_hours: float):
        self.dt_hours = dt_hours

    def act(self, observation: EnergyObservationV1) -> AgentActionV1:
        escalation = self._check_information_sufficiency(observation)
        if escalation is not None:
            return escalation

        gen = observation.network_model.generators[0]
        policy = observation.operational_policy
        forecast = observation.market.price_forecast_gbp_mwh
        price = forecast if forecast is not None else observation.market.reference_price_gbp_mwh

        if price is not None and price > 0 and not policy.temporary_limits.generation_increase_prohibited:
            increase = self._max_increase_mw(observation)
            if increase > 1e-9:
                return AgentActionV1(action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output + increase)

        if price is not None and price < 0 and not policy.temporary_limits.generation_decrease_prohibited:
            decrease = self._max_decrease_mw(observation)
            if decrease > 1e-9:
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
        candidates = [gen.mw_max - gen.mw_output, gen.mw_ramp_up_limit_per_step]
        for bus in observation.network_model.buses:
            if bus.bus_id == gen.bus_id and gen.voltage_sensitivity_pu_per_mw > 0:
                candidates.append((bus.voltage_max_pu - bus.voltage_pu) / gen.voltage_sensitivity_pu_per_mw)
        for branch in observation.network_model.branches:
            if branch.sensitivity_mva_per_mw > 0:
                candidates.append((branch.mva_limit - branch.mva_flow) / branch.sensitivity_mva_per_mw)
        return max(0.0, min(candidates))

    def _max_decrease_mw(self, observation: EnergyObservationV1) -> float:
        gen = observation.network_model.generators[0]
        floor = max(gen.mw_min, observation.operational_policy.reserve_mw_margin or gen.mw_min)
        candidates = [gen.mw_output - floor, gen.mw_ramp_down_limit_per_step]
        for bus in observation.network_model.buses:
            if bus.bus_id == gen.bus_id and gen.voltage_sensitivity_pu_per_mw > 0:
                candidates.append((bus.voltage_pu - bus.voltage_min_pu) / gen.voltage_sensitivity_pu_per_mw)
        for branch in observation.network_model.branches:
            if branch.sensitivity_mva_per_mw < 0:
                candidates.append((branch.mva_limit - branch.mva_flow) / -branch.sensitivity_mva_per_mw)
        return max(0.0, min(candidates))
