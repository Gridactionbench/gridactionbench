"""IgnoreThermalLimitAgent — seeded failure agent. See master brief §27.

Renamed from IgnoreNetworkAgent for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md) — same failure mode, translated:
makes otherwise nameplate/ramp-aware, price-responsive decisions (mirroring
RuleBasedAgent's trigger logic) but never consults any branch's `sensitivity_mva_per_mw`
when computing its requested MW, so it never anticipates a thermal-limit consequence.

Expected failure mode: NET-BRANCH-THERMAL-LIMIT-001 failures (and resulting UCVs) whenever
the true branch thermal limit is more restrictive than the nameplate/ramp limit — e.g.
GB-BESS-NET-007 through NET-010, where this is precisely the scenario design.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1


class IgnoreThermalLimitAgent:
    agent_id = "ignore-thermal-limit"
    agent_version = "0.2.0"
    agent_type = "seeded_failure"

    def __init__(self, dt_hours: float):
        self.dt_hours = dt_hours

    def act(self, observation: EnergyObservationV1) -> AgentActionV1:
        gen = observation.network_model.generators[0]
        policy = observation.operational_policy
        price = observation.market.reference_price_gbp_mwh

        if price is not None and price > 0 and not policy.temporary_limits.generation_increase_prohibited:
            increase = self._max_increase_ignoring_thermal_limit(observation)
            if increase > 1e-9:
                return AgentActionV1(action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output + increase)

        if price is not None and price < 0 and not policy.temporary_limits.generation_decrease_prohibited:
            decrease = self._max_decrease_ignoring_thermal_limit(observation)
            if decrease > 1e-9:
                return AgentActionV1(action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output - decrease)

        return AgentActionV1(action=ActionType.IDLE)

    def _max_increase_ignoring_thermal_limit(self, observation: EnergyObservationV1) -> float:
        gen = observation.network_model.generators[0]
        # deliberately no branch sensitivity term
        return max(0.0, min(gen.mw_max - gen.mw_output, gen.mw_ramp_up_limit_per_step))

    def _max_decrease_ignoring_thermal_limit(self, observation: EnergyObservationV1) -> float:
        gen = observation.network_model.generators[0]
        floor = max(gen.mw_min, observation.operational_policy.reserve_mw_margin or gen.mw_min)
        # deliberately no branch sensitivity term
        return max(0.0, min(gen.mw_output - floor, gen.mw_ramp_down_limit_per_step))
