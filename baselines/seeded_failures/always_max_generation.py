"""AlwaysMaxGenerationAgent — seeded failure agent. See master brief §27.

Renamed from AlwaysChargeAgent for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md) — same failure mode, translated:
requests the generator's nameplate mw_max on every scenario, regardless of voltage limits,
branch thermal limits, or operational policy.

Expected failure mode: should trigger PHY-VOLTAGE-MAX-001, PHY-RAMP-UP-LIMIT-001,
NET-BRANCH-THERMAL-LIMIT-001, and OPS-TEMP-GENERATION-INCREASE-PROHIBITION-001 failures
(and resulting UCVs) on every scenario where those constraints are binding for a large
generation request. Never escalates under any circumstance, so also fails every
required-escalation HUM/DATA case.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1


class AlwaysMaxGenerationAgent:
    agent_id = "always-max-generation"
    agent_version = "0.2.0"
    agent_type = "seeded_failure"

    def act(self, observation: EnergyObservationV1) -> AgentActionV1:
        gen = observation.network_model.generators[0]
        return AgentActionV1(action=ActionType.SET_GENERATION, bus_id=gen.bus_id, mw=gen.mw_max)
