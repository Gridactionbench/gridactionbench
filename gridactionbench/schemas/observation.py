"""EnergyObservationV1 — the agent-visible schema.

Field listing and semantics: docs/suites/gb-bess/SPECIFICATION.md §2.
Replaces the single-battery `battery`/`network` blocks with a `NetworkModel` describing a
small, self-contained, synthetic PSS/E power-flow case (buses, branches, generators) — see
docs/architecture/adr/ADR-018-psse-power-flow-adapter.md. Addressing within `NetworkModel`
(`bus_id`, `branch_id`) refers only to elements of this loaded synthetic case, never a
real-world device or endpoint (docs/architecture/adr/ADR-015-physical-system-isolation.md
still applies and is unaffected by this change).

Per SPECIFICATION.md's Phase 0.5 note: the fields under `telemetry` describe what was
OBSERVED. Whether a given age/status counts as "too stale to act on" is never decided by
this schema — it is decided per-scenario by that scenario's own `information_requirements`
block (see gridactionbench.core.scenario.InformationRequirements).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FiniteModel(BaseModel):
    """Reject non-finite inputs before numeric comparisons or solver calls."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Bus(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    bus_id: int
    voltage_pu: float = Field(gt=0.0)
    voltage_min_pu: float = Field(gt=0.0)
    voltage_max_pu: float = Field(gt=0.0)


class Branch(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: str
    from_bus: int
    to_bus: int
    # Signed: direction follows `sensitivity_mva_per_mw`'s sign convention below. Compared
    # against `mva_limit` by magnitude (gridactionbench.evaluators.gb_bess.net), since
    # `mva_limit` is this branch's thermal rating irrespective of flow direction.
    mva_flow: float
    # A zero thermal limit is a legitimate, real connection condition (e.g. a zero export
    # limit under a flexible/ANM connection agreement) — see GB-BESS-NET-007/009.
    mva_limit: float = Field(ge=0.0)
    # Linear sensitivity of this branch's loading to the scenario's one controllable
    # generator's MW output (a distribution-factor-style figure, as a real connection
    # agreement would derive from an offline power-flow study) — lets an agent estimate
    # headroom directly from the Observation without running its own power-flow solve.
    # 0.0 for a branch this generator has no meaningful effect on. Negative represents a
    # branch that is loaded *more* as this generator's output *decreases* (e.g. an
    # upstream branch covering local load the generator isn't currently meeting) —
    # modeled as `mva_flow = baseline_mva + sensitivity_mva_per_mw * mw_output`.
    sensitivity_mva_per_mw: float = 0.0
    # The flow this branch would carry if the connected generator output zero MW (fixed
    # background/load flow). 0.0 for a branch with no such baseline (the common case).
    baseline_mva: float = 0.0


class Generator(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    bus_id: int
    mw_output: float
    mw_min: float = Field(ge=0.0)
    mw_max: float = Field(gt=0.0)
    # Real generators commonly ramp up and down at different rates (e.g. a thermal plant
    # ramping down faster than it can ramp up) — modeled as two independent limits rather
    # than one symmetric one.
    mw_ramp_up_limit_per_step: float = Field(ge=0.0)
    mw_ramp_down_limit_per_step: float = Field(ge=0.0)
    # Linear sensitivity of this generator's own bus voltage to its own MW output — same
    # offline-study-derived-figure rationale as Branch.sensitivity_mva_per_mw above.
    voltage_sensitivity_pu_per_mw: float = 0.0


class NetworkModel(FiniteModel):
    """A small, self-contained, synthetic power-flow case. Not real grid topology — see
    module docstring. Solved by `gridactionbench.simulators.psse_simulator.PSSESimulatorAdapter`
    (real PSS/E via `psspy`) or, in tests, a fake `psspy` double."""

    model_config = ConfigDict(extra="forbid")

    buses: list[Bus] = Field(default_factory=list)
    branches: list[Branch] = Field(default_factory=list)
    generators: list[Generator] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> "NetworkModel":
        bus_ids = [bus.bus_id for bus in self.buses]
        if any(bus_id <= 0 for bus_id in bus_ids) or len(set(bus_ids)) != len(bus_ids):
            raise ValueError("bus IDs must be positive and unique")
        branch_ids = [branch.branch_id for branch in self.branches]
        if len(set(branch_ids)) != len(branch_ids):
            raise ValueError("branch IDs must be unique")
        gen_ids = [gen.bus_id for gen in self.generators]
        if len(set(gen_ids)) != len(gen_ids):
            raise ValueError("only one controllable generator per bus is supported")
        known = set(bus_ids)
        if any(gen.bus_id not in known for gen in self.generators):
            raise ValueError("generator references an unknown bus")
        if any(br.from_bus not in known or br.to_bus not in known for br in self.branches):
            raise ValueError("branch references an unknown bus")
        return self

    def bus(self, bus_id: int) -> Bus:
        return next(b for b in self.buses if b.bus_id == bus_id)

    def generator(self, bus_id: int) -> Generator:
        return next(g for g in self.generators if g.bus_id == bus_id)


class MarketState(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    reference_price_gbp_mwh: Optional[float] = None
    # A previously-issued forecast for this step's price, distinct from the actual/real-time
    # reference_price_gbp_mwh above. None for every scenario/episode not declaring one.
    price_forecast_gbp_mwh: Optional[float] = None


class TelemetryFieldStatus(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    voltage: str = "fresh"
    branch_flow: str = "fresh"
    market: str = "fresh"


class TelemetryAgeSeconds(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    voltage: Optional[int] = None
    branch_flow: Optional[int] = None


class Telemetry(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    field_status: TelemetryFieldStatus = Field(default_factory=TelemetryFieldStatus)
    age_seconds: TelemetryAgeSeconds = Field(default_factory=TelemetryAgeSeconds)
    missing_fields: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    # Second-reading support for conflicting-telemetry scenarios (formerly
    # soc_reading_1/2). v0.2 supports exactly two voltage readings for one bus —
    # N-way conflict is a future extension, not modeled here.
    voltage_reading_1: Optional[float] = None
    voltage_reading_2: Optional[float] = None


class TemporaryLimits(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    generation_increase_prohibited: bool = False
    generation_decrease_prohibited: bool = False
    max_mw_override: Optional[float] = None


class OperationalPolicy(FiniteModel):
    model_config = ConfigDict(extra="forbid")

    # Analogous to the former reserve_soc: a generator-output floor stricter than mw_min.
    reserve_mw_margin: Optional[float] = None
    temporary_limits: TemporaryLimits = Field(default_factory=TemporaryLimits)
    approval_required: bool = False


class EnergyObservationV1(FiniteModel):
    """Agent-visible observation. See docs/suites/gb-bess/SPECIFICATION.md §2.

    schema_version bumped to 2.0.0: breaking change (battery -> network_model), per
    docs/benchmark/VERSIONING.md's MAJOR-change rule.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "2.0.0"
    benchmark: str = "gridactionbench"
    benchmark_version: str
    suite: str = "gb-bess"
    suite_version: str

    scenario_id: str
    timestamp: datetime

    network_model: NetworkModel
    market: MarketState = Field(default_factory=MarketState)
    telemetry: Telemetry = Field(default_factory=Telemetry)
    operational_policy: OperationalPolicy = Field(default_factory=OperationalPolicy)

    # Adversarial/injected content — present only on ADV-family scenarios. Never
    # authoritative; never parsed by any evaluator's pass/fail logic.
    injected_field: Optional[str] = None
