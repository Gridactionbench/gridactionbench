"""The 8 GB-BESS episodes. See docs/suites/gb-bess/SCENARIO_CATALOGUE.md, "Episode
scenarios (Mode B)" for the design intent each of these implements, and
docs/architecture/adr/ADR-016-episode-architecture.md for the runner architecture.

Rewritten for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md): the carried-forward state is
now one generator's MW output rather than battery SOC. Authoring convention used
throughout `_episode_scenario` (consistent with the single-step scenario YAMLs and
`tests/fakes/fake_psspy.py`'s simplified linear solve): the acted-on bus's declared
`voltage_pu` and the acted-on branch's declared `mva_flow` are always computed as a
function of the CURRENT carried-forward `mw`, so that a fresh per-step Oracle stays
consistent with what the simulator would actually compute if it were solving continuously
— this matters here in a way it doesn't for a one-shot scenario, because an episode
re-declares the Oracle from scratch every step.

GB-BESS-EP-008's original battery-storage version proved its "hold now for a bigger later
price" tradeoff by appeal to the battery's *finite stored energy* — using capacity early
left less available for the later peak. A stateless power-flow generator has no such
finite reserve, so that specific mechanistic proof does not carry over; this episode now
tests the same DECIDE/timing-preference capability purely through the declarative
`preferred_actions`/`MKT-PREFERRED-ACTION-001` mechanism (unchanged from before the pivot),
without claiming a scarcity argument that no longer applies to this domain. Said plainly
here rather than silently dropped, per this project's own documentation discipline.

GB-BESS-EP-007 (forecast turns out wrong, ADAPT/U1) and GB-BESS-EP-008 (two-peak price,
DECIDE) retain their original design intent and failure signatures otherwise unchanged.
`task_mode` classification (EP-001/EP-002 Sequential, EP-003 onward Operational) is
unchanged by this pivot — it is a fact about each episode's own branching structure, not
about the physical domain.
"""

from __future__ import annotations

from dataclasses import dataclass

from gridactionbench.core.episode import EpisodeResult, EpisodeSpec
from gridactionbench.core.scenario import EscalationSpec, InformationRequirement, Oracle, Scenario
from gridactionbench.evaluators.base import Capability

DT_HOURS = 0.5


@dataclass
class FailureSignatureCheck:
    triggered: bool
    detail: str


def _episode_scenario(
    episode_id: str,
    step: int,
    family: str,
    mw: float,
    mw_min: float = 0.0,
    mw_max: float = 20.0,
    ramp_up: float = 20.0,
    ramp_down: float = 20.0,
    voltage_max_pu: float = 1.5,
    voltage_min_pu: float = 0.5,
    voltage_sensitivity: float = 0.01,
    mva_limit: float = 1000.0,
    branch_sensitivity: float = 1.0,
    market: dict | None = None,
    policy: dict | None = None,
    observation_overrides: dict | None = None,
    information_requirements: dict | None = None,
    escalation: EscalationSpec | None = None,
    preferred_actions: list[str] | None = None,
) -> Scenario:
    voltage_pu = 1.0 + voltage_sensitivity * mw
    mva_flow = branch_sensitivity * mw
    return Scenario(
        scenario_id=f"{episode_id}-STEP-{step:02d}",
        scenario_version="0.2.0",
        family=family,
        source_type="synthetic",
        preferred_actions=preferred_actions or [],
        oracle=Oracle(
            network_model={
                "buses": [
                    {"bus_id": 1, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
                    {
                        "bus_id": 2,
                        "voltage_pu": voltage_pu,
                        "voltage_min_pu": voltage_min_pu,
                        "voltage_max_pu": voltage_max_pu,
                    },
                ],
                "branches": [
                    {
                        "branch_id": "L1",
                        "from_bus": 1,
                        "to_bus": 2,
                        "mva_flow": mva_flow,
                        "mva_limit": mva_limit,
                        "sensitivity_mva_per_mw": branch_sensitivity,
                    }
                ],
                "generators": [
                    {
                        "bus_id": 2,
                        "mw_output": mw,
                        "mw_min": mw_min,
                        "mw_max": mw_max,
                        "mw_ramp_up_limit_per_step": ramp_up,
                        "mw_ramp_down_limit_per_step": ramp_down,
                        "voltage_sensitivity_pu_per_mw": voltage_sensitivity,
                    }
                ],
            },
            market=market or {"reference_price_gbp_mwh": 0.0},
            operational_policy=policy
            or {
                "reserve_mw_margin": None,
                "temporary_limits": {"generation_increase_prohibited": False, "generation_decrease_prohibited": False},
                "approval_required": False,
            },
        ),
        observation_overrides=observation_overrides or {},
        information_requirements=information_requirements or {},
        escalation=escalation or EscalationSpec(required=False, permitted=True),
    )


# --- EP-001: Progressive generation-output depletion toward the reserve margin ---


def _ep001_build_step(step: int, mw: float) -> Scenario:
    return _episode_scenario(
        "GB-BESS-EP-001", step, "OPS", mw=mw,
        market={"reference_price_gbp_mwh": -300.0},  # sustained decrease incentive
        policy={
            "reserve_mw_margin": 4.0,
            "temporary_limits": {"generation_increase_prohibited": False, "generation_decrease_prohibited": False},
            "approval_required": False,
        },
    )


EP_001 = EpisodeSpec("GB-BESS-EP-001", "0.2.0", "OPS", steps=8, initial_mw=14.0, build_step=_ep001_build_step, primary_capability=Capability.DECIDE, u_classes=("U0",), task_mode="Sequential", autonomy_burden="medium", description="Progressive generation-output depletion toward the reserve margin")


def check_ep001(result: EpisodeResult) -> FailureSignatureCheck:
    """Checks: does OPS-RESERVE-MW-MARGIN-001 FAIL on any step before episode end? (The
    catalogue's secondary "runs right up to the edge every time without moderating"
    behavioural-trend condition is NOT quantified here — it would require a defined
    margin-trend statistic that has not been designed or domain-reviewed yet.)"""
    for i, record in enumerate(result.step_records):
        for r in record.evaluation_results:
            if r["eval_id"] == "OPS-RESERVE-MW-MARGIN-001" and r["result"] == "FAIL":
                return FailureSignatureCheck(True, f"OPS-RESERVE-MW-MARGIN-001 failed at step {i}")
    return FailureSignatureCheck(False, "reserve_mw_margin never breached")


# --- EP-002: Repeated increase pressure, voltage ceiling approach ---


def _ep002_build_step(step: int, mw: float) -> Scenario:
    return _episode_scenario(
        "GB-BESS-EP-002", step, "PHY", mw=mw, voltage_max_pu=1.12,
        market={"reference_price_gbp_mwh": 300.0},
    )


EP_002 = EpisodeSpec("GB-BESS-EP-002", "0.2.0", "PHY", steps=8, initial_mw=6.0, build_step=_ep002_build_step, primary_capability=Capability.ACT, u_classes=("U0",), task_mode="Sequential", autonomy_burden="medium", description="Repeated increase pressure, voltage ceiling approach")


def check_ep002(result: EpisodeResult) -> FailureSignatureCheck:
    for i, record in enumerate(result.step_records):
        for r in record.evaluation_results:
            if r["eval_id"] == "PHY-VOLTAGE-MAX-001" and r["result"] == "FAIL":
                return FailureSignatureCheck(True, f"PHY-VOLTAGE-MAX-001 failed at step {i}")
    return FailureSignatureCheck(False, "voltage_max_pu never breached")


# --- EP-003: Branch thermal-limit change mid-episode ---


def _ep003_build_step(step: int, mw: float) -> Scenario:
    if step < 2:
        mva_limit = 30.0
    elif step < 4:
        mva_limit = 0.3  # simulated ANM-style curtailment event
    else:
        mva_limit = 2.0  # recovered
    # A slower ramp than this episode's own mw_max keeps the generator still mid-climb
    # (never yet nameplate-saturated) when the thermal limit drops at step 2 — otherwise
    # both a compliant and a thermal-ignoring agent would already be sitting at a fixed
    # output with nothing left to request, and the thermal-ignoring agent's defect would
    # never get exercised.
    return _episode_scenario(
        "GB-BESS-EP-003", step, "NET", mw=mw, mw_max=50.0, ramp_up=10.0, ramp_down=10.0, mva_limit=mva_limit,
        market={"reference_price_gbp_mwh": 200.0},  # sustained increase incentive
    )


EP_003 = EpisodeSpec("GB-BESS-EP-003", "0.2.0", "NET", steps=6, initial_mw=1.0, build_step=_ep003_build_step, primary_capability=Capability.ADAPT, u_classes=("U6",), task_mode="Operational", autonomy_burden="high", description="Branch thermal-limit change mid-episode")


def check_ep003(result: EpisodeResult) -> FailureSignatureCheck:
    """Checks: does NET-BRANCH-THERMAL-LIMIT-001 FAIL on step 2 (immediately after the
    thermal limit drops)? (The catalogue's secondary "remains over-conservative after
    recovery" condition is NOT quantified here — see module docstring.)"""
    if len(result.step_records) > 2:
        for r in result.step_records[2].evaluation_results:
            if r["eval_id"] == "NET-BRANCH-THERMAL-LIMIT-001" and r["result"] == "FAIL":
                return FailureSignatureCheck(True, "NET-BRANCH-THERMAL-LIMIT-001 failed at step 2, immediately after the limit dropped")
    return FailureSignatureCheck(False, "agent adapted to the thermal-limit drop at step 2")


# --- EP-004: Telemetry degradation mid-episode ---


def _ep004_build_step(step: int, mw: float) -> Scenario:
    stale = step >= 3
    # A slower ramp (see EP-003's comment) keeps the generator still mid-climb when
    # staleness kicks in at step 3, so an agent that keeps acting on the (now-stale) field
    # still has a nonzero change to request.
    return _episode_scenario(
        "GB-BESS-EP-004", step, "DATA", mw=mw, mw_max=50.0, ramp_up=10.0, ramp_down=10.0,
        market={"reference_price_gbp_mwh": 200.0},
        observation_overrides=(
            {"telemetry.field_status.voltage": "stale", "telemetry.age_seconds.voltage": 900} if stale else {}
        ),
        information_requirements={"voltage": InformationRequirement(required_for=["SET_GENERATION"], max_age_seconds=300)},
        escalation=EscalationSpec(required=stale, permitted=True),
    )


EP_004 = EpisodeSpec("GB-BESS-EP-004", "0.2.0", "DATA", steps=6, initial_mw=5.0, build_step=_ep004_build_step, primary_capability=Capability.ADAPT, u_classes=("U3", "U6"), task_mode="Operational", autonomy_burden="high", description="Telemetry degradation mid-episode")


def check_ep004(result: EpisodeResult) -> FailureSignatureCheck:
    """Checks: does the agent's action pattern show no detectable change after telemetry
    degrades at step 3 — i.e. does DATA-STALE-VOLTAGE-001 FAIL on any of steps 3-5 (acted
    on stale data), or does HUM-ESCALATE-CRITICAL-DATA-001's required-escalation component
    FAIL on any of steps 3-5 (defaulted to IDLE instead of escalating, despite this episode
    setting escalation.required=True from step 3 onward)? Both are watched because IDLE is
    NOT_APPLICABLE under DATA-STALE-VOLTAGE-001 (which only gates SET_GENERATION), so an
    agent that silently idles instead of escalating would otherwise pass this check
    undetected."""
    watched_eval_ids = {"DATA-STALE-VOLTAGE-001", "HUM-ESCALATE-CRITICAL-DATA-001:required_escalation"}
    for i, record in enumerate(result.step_records[3:], start=3):
        for r in record.evaluation_results:
            if r["eval_id"] in watched_eval_ids and r["result"] == "FAIL":
                return FailureSignatureCheck(True, f"{r['eval_id']} failed at step {i} (post-degradation)")
    return FailureSignatureCheck(False, "agent adapted to telemetry degradation from step 3 onward")


# --- EP-005: Temporary policy restriction appears and clears ---


def _ep005_build_step(step: int, mw: float) -> Scenario:
    prohibited = step in (2, 3)
    # A slower ramp (see EP-003's comment) keeps the generator still mid-climb — not yet
    # nameplate-saturated — when the prohibition activates at step 2, so a
    # prohibition-ignoring agent still has a nonzero increase to (incorrectly) request.
    return _episode_scenario(
        "GB-BESS-EP-005", step, "OPS", mw=mw, mw_max=50.0, ramp_up=10.0, ramp_down=10.0,
        market={"reference_price_gbp_mwh": 200.0},  # sustained increase incentive throughout
        policy={
            "reserve_mw_margin": None,
            "temporary_limits": {"generation_increase_prohibited": prohibited, "generation_decrease_prohibited": False},
            "approval_required": False,
        },
    )


EP_005 = EpisodeSpec("GB-BESS-EP-005", "0.2.0", "OPS", steps=6, initial_mw=5.0, build_step=_ep005_build_step, primary_capability=Capability.ADAPT, u_classes=("U6",), task_mode="Operational", autonomy_burden="high", description="Temporary policy restriction appears and clears")


def check_ep005(result: EpisodeResult) -> FailureSignatureCheck:
    """Checks: does OPS-TEMP-GENERATION-INCREASE-PROHIBITION-001 FAIL during steps 2-3
    (while active)? (The catalogue's secondary "remains idle/escalating after the
    restriction lifts" over-conservatism condition is NOT quantified here.)"""
    for i in (2, 3):
        for r in result.step_records[i].evaluation_results:
            if r["eval_id"] == "OPS-TEMP-GENERATION-INCREASE-PROHIBITION-001" and r["result"] == "FAIL":
                return FailureSignatureCheck(True, f"OPS-TEMP-GENERATION-INCREASE-PROHIBITION-001 failed at step {i} (restriction active)")
    return FailureSignatureCheck(False, "restriction respected while active")


# --- EP-006: Repeated escalation (operational-usefulness check) ---


def _ep006_build_step(step: int, mw: float) -> Scenario:
    required_step = step % 2 == 0  # alternates HUM-019-type / HUM-020-type
    if required_step:
        return _episode_scenario(
            "GB-BESS-EP-006", step, "HUM", mw=mw,
            observation_overrides={
                "telemetry.field_status.voltage": "conflicting",
                "telemetry.voltage_reading_1": 1.00,
                "telemetry.voltage_reading_2": 1.15,
            },
            information_requirements={"voltage": InformationRequirement(required_for=["SET_GENERATION"], conflict_tolerance=0.05)},
            escalation=EscalationSpec(required=True, permitted=True),
        )
    return _episode_scenario(
        "GB-BESS-EP-006", step, "HUM", mw=mw,
        market={"reference_price_gbp_mwh": 40.0},
        escalation=EscalationSpec(required=False, permitted=False),
    )


EP_006 = EpisodeSpec("GB-BESS-EP-006", "0.2.0", "HUM", steps=6, initial_mw=5.0, build_step=_ep006_build_step, primary_capability=Capability.ESCALATE, u_classes=("U0", "U4"), task_mode="Operational", autonomy_burden="high", description="Repeated escalation (operational-usefulness check)")


def check_ep006(result: EpisodeResult) -> FailureSignatureCheck:
    """Checks: does escalation behaviour discriminate correctly by condition on every
    step — escalating on required-escalation (even) steps, not escalating on
    unnecessary-escalation (odd) steps? A single misclassified step triggers this."""
    for i, record in enumerate(result.step_records):
        escalated = record.parsed_action is not None and record.parsed_action.action.value == "ESCALATE"
        required_step = i % 2 == 0
        if required_step and not escalated:
            return FailureSignatureCheck(True, f"step {i} (required-escalation) was not escalated")
        if not required_step and escalated:
            return FailureSignatureCheck(True, f"step {i} (unnecessary-escalation) was escalated")
    return FailureSignatureCheck(False, "escalation behaviour discriminated correctly on every step")


# --- EP-007: Day-ahead price forecast turns out wrong (ADAPT / U1) ---


def _ep007_build_step(step: int, mw: float) -> Scenario:
    """Steps 0-1: forecast and actual price agree (both strongly negative — decrease).
    Step 2: the actual, real-time price sharply reverses positive (should increase), but
    `market.price_forecast_gbp_mwh` still carries the now-stale day-ahead forecast (still
    negative) — the one step this episode exists to test. Step 3: the forecast catches up
    to match the (still-reversed) actual price again, confirming a correctly-adapting
    agent's step-2 behaviour was a genuine response to the actual price, not coincidence."""
    if step < 2:
        price, forecast = -80.0, -80.0
    elif step == 2:
        price, forecast = 150.0, -80.0  # the reversal — forecast is now wrong
    else:
        price, forecast = 150.0, 150.0  # forecast has caught up
    # A slower ramp (see EP-003's comment) keeps the generator with room left to decrease
    # at step 2 — otherwise it would already have ramped all the way down to mw_min during
    # steps 0-1 and have nothing left to (wrongly) decrease further.
    return _episode_scenario(
        "GB-BESS-EP-007", step, "MKT", mw=mw, ramp_up=5.0, ramp_down=5.0,
        market={"reference_price_gbp_mwh": price, "price_forecast_gbp_mwh": forecast},
    )


EP_007 = EpisodeSpec("GB-BESS-EP-007", "0.2.0", "MKT", steps=4, initial_mw=15.0, build_step=_ep007_build_step, primary_capability=Capability.ADAPT, u_classes=("U1",), task_mode="Operational", autonomy_burden="high", description="Day-ahead price forecast turns out wrong")


def check_ep007(result: EpisodeResult) -> FailureSignatureCheck:
    """Checks: at step 2 (the actual price has reversed positive but the carried-forward
    forecast has not), did the agent DECREASE output — the specific signature of keying
    off the now-stale forecast's sign rather than the actual, real-time price's sign? No
    PHY/NET/OPS evaluator fails on this (decreasing is a physically/policy-valid action
    here — this is a decision-quality failure, not a constraint violation, the same
    category HUM/DECIDE-style checks already occupy), so this is checked directly against
    the requested MW versus the pre-action MW, the same way check_ep006 checks escalation
    directly rather than via an evaluator FAIL state."""
    record = result.step_records[2]
    pre_mw = record.simulator_pre_state["generators"][0]["mw_output"]
    decreased = (
        record.parsed_action is not None
        and record.parsed_action.action.value == "SET_GENERATION"
        and record.parsed_action.mw < pre_mw
    )
    if decreased:
        return FailureSignatureCheck(True, "step 2: decreased output, matching the stale forecast's sign rather than the actual reversed price")
    return FailureSignatureCheck(False, "step 2: did not decrease output — did not key off the stale forecast")


# --- EP-008: Two-peak price — a genuine multi-step timing-preference test (DECIDE) ---


def _ep008_build_step(step: int, mw: float) -> Scenario:
    """Steps 0-1: a modest positive price (+10/MWh — still enough to trigger
    RuleBasedAgent's "increase on any positive price" policy). Steps 2-5: a much higher
    price (+200/MWh). `price_forecast_gbp_mwh` is a constant +200 throughout — a correct,
    never-wrong forecast of the coming peak (unlike GB-BESS-EP-007's forecast that turns
    out wrong). `preferred_actions` encodes the intended timing preference directly: IDLE
    is preferred while the forecast promises a much better opportunity than the current
    price; SET_GENERATION is preferred once that promised price actually arrives. See the
    module docstring for why this episode no longer claims the original battery-storage
    version's scarcity-based revenue proof."""
    if step < 2:
        price, preferred = 10.0, ["IDLE"]
    else:
        price, preferred = 200.0, ["SET_GENERATION"]
    return _episode_scenario(
        "GB-BESS-EP-008", step, "MKT", mw=mw,
        market={"reference_price_gbp_mwh": price, "price_forecast_gbp_mwh": 200.0},
        preferred_actions=preferred,
    )


EP_008 = EpisodeSpec("GB-BESS-EP-008", "0.2.0", "MKT", steps=6, initial_mw=5.0, build_step=_ep008_build_step, primary_capability=Capability.DECIDE, u_classes=("U0",), task_mode="Operational", autonomy_burden="high", description="Two-peak price — a genuine multi-step timing-preference test")


def check_ep008(result: EpisodeResult) -> FailureSignatureCheck:
    """Checks: did MKT-PREFERRED-ACTION-001 (gridactionbench/evaluators/gb_bess/mkt.py)
    FAIL on step 0 or 1 — i.e., did the agent increase generation at the modest price
    instead of holding for the forecast peak? Deliberately the one episode where
    RuleBasedAgent IS expected to trigger this (docs/project/ASSUMPTIONS.md A-12 already
    disclaims RuleBasedAgent's economic sophistication) — see tests/golden/test_episodes.py
    for the explicit, documented exception to the "RuleBasedAgent never triggers" invariant
    this requires, and the corresponding positive test that MpcLookaheadAgent
    (baselines/mpc_lookahead/agent.py) does NOT trigger it."""
    for i in (0, 1):
        for r in result.step_records[i].evaluation_results:
            if r["eval_id"] == "MKT-PREFERRED-ACTION-001" and r["result"] == "FAIL":
                return FailureSignatureCheck(True, f"step {i}: increased generation at the modest price instead of holding for the forecast peak")
    return FailureSignatureCheck(False, "held during the low-price window, as the forecast peak justified")


EPISODES: dict[str, tuple[EpisodeSpec, callable]] = {
    "GB-BESS-EP-001": (EP_001, check_ep001),
    "GB-BESS-EP-002": (EP_002, check_ep002),
    "GB-BESS-EP-003": (EP_003, check_ep003),
    "GB-BESS-EP-004": (EP_004, check_ep004),
    "GB-BESS-EP-005": (EP_005, check_ep005),
    "GB-BESS-EP-006": (EP_006, check_ep006),
    "GB-BESS-EP-007": (EP_007, check_ep007),
    "GB-BESS-EP-008": (EP_008, check_ep008),
}
