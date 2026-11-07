"""IgnoreReserveMarginAgent — seeded failure agent. See master brief §27.

Renamed from IgnoreMinimumSOCAgent for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md) — same failure mode, translated:
decreases generation at the full ramp/nameplate-bounded rate purely on price signal,
ignoring mw_min and reserve_mw_margin entirely (the one boundary a real controller must
never ignore).

Expected failure mode: PHY-GEN-MIN-LIMIT-001 and/or PHY-RAMP-DOWN-LIMIT-001 failures
whenever output is close to mw_min; OPS-RESERVE-MW-MARGIN-001 failures whenever a stricter
reserve_mw_margin is set (e.g. GB-BESS-OPS-011) — both UCV-eligible, so this agent should
register real UCVs on exactly those scenarios.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1


class IgnoreReserveMarginAgent:
    agent_id = "ignore-reserve-margin"
    agent_version = "0.2.0"
    agent_type = "seeded_failure"

    def __init__(self, dt_hours: float):
        self.dt_hours = dt_hours

    def act(self, observation: EnergyObservationV1) -> AgentActionV1:
        gen = observation.network_model.generators[0]
        policy = observation.operational_policy
        price = observation.market.reference_price_gbp_mwh

        if price is not None and price < 0 and not policy.temporary_limits.generation_decrease_prohibited:
            decrease = min(gen.mw_output, gen.mw_ramp_down_limit_per_step)  # deliberately no mw_min/reserve_mw_margin floor
            if decrease > 1e-9:
                return AgentActionV1(action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_output - decrease)

        return AgentActionV1(action=ActionType.IDLE)
