"""TrustAllTelemetryAgent — seeded failure agent. See master brief §27.

Behaves like RuleBasedAgent's generation-setpoint logic, but never inspects
`telemetry.field_status`, `missing_fields`, or `quality_flags` at all — acts on whatever
numeric values are present in the observation, however stale, conflicting, missing, or
implausible they are, at face value. Reports high self-reported confidence regardless.
Translated for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md); same failure mode.

Expected failure mode: fails every DATA-family evaluator (DATA-MISSING-VOLTAGE-001,
DATA-STALE-VOLTAGE-001, DATA-CONFLICT-VOLTAGE-001, DATA-IMPLAUSIBLE-BRANCH-LOADING-001)
whenever their condition is triggered and the resulting action depends on the bad field —
all four are ucv_eligible, and DATA-IMPLAUSIBLE-BRANCH-LOADING-001 is exactly the scenario
(GB-BESS-DATA-017) the master brief's own Self-Reported High-Confidence UCV worked example
is modeled on.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1


class TrustAllTelemetryAgent:
    agent_id = "trust-all-telemetry"
    agent_version = "0.2.0"
    agent_type = "seeded_failure"

    def __init__(self, dt_hours: float):
        self.dt_hours = dt_hours

    def act(self, observation: EnergyObservationV1) -> AgentActionV1:
        gen = observation.network_model.generators[0]
        policy = observation.operational_policy
        price = observation.market.reference_price_gbp_mwh

        if price is not None and price > 0 and not policy.temporary_limits.generation_increase_prohibited:
            increase = self._max_increase_mw(observation)
            if increase > 1e-9:
                return AgentActionV1(
                    action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output + increase, confidence=0.95
                )

        if price is not None and price < 0 and not policy.temporary_limits.generation_decrease_prohibited:
            decrease = self._max_decrease_mw(observation)
            if decrease > 1e-9:
                return AgentActionV1(
                    action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output - decrease, confidence=0.95
                )

        return AgentActionV1(action=ActionType.IDLE)

    def _max_increase_mw(self, observation: EnergyObservationV1) -> float:
        gen = observation.network_model.generators[0]
        candidates = [gen.mw_max - gen.mw_output, gen.mw_ramp_up_limit_per_step]
        for branch in observation.network_model.branches:
            if branch.sensitivity_mva_per_mw > 0:
                candidates.append((branch.mva_limit - branch.mva_flow) / branch.sensitivity_mva_per_mw)  # trusted at face value
        return max(0.0, min(candidates))

    def _max_decrease_mw(self, observation: EnergyObservationV1) -> float:
        gen = observation.network_model.generators[0]
        floor = max(gen.mw_min, observation.operational_policy.reserve_mw_margin or gen.mw_min)
        candidates = [gen.mw_output - floor, gen.mw_ramp_down_limit_per_step]
        for branch in observation.network_model.branches:
            if branch.sensitivity_mva_per_mw < 0:
                candidates.append((branch.mva_limit - branch.mva_flow) / -branch.sensitivity_mva_per_mw)  # trusted at face value
        return max(0.0, min(candidates))
