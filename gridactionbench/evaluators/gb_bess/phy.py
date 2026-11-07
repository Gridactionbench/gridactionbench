"""PHY — physical constraint evaluators. See docs/suites/gb-bess/EVALUATION_SPEC.md, "PHY".

Rewritten for the PSS/E power-flow pivot (docs/architecture/adr/ADR-018-psse-power-flow-adapter.md):
voltage-limit and generator-dispatch-limit checks replace the former SOC/charge/discharge
formulas. Each evaluator here still mirrors its pre-pivot counterpart's *structural role*
(resulting-state ceiling/floor check, requested-value rate-limit check, requested-change
ramp-feasibility check) — only the physical quantities changed.
"""

from __future__ import annotations

from gridactionbench.evaluators.base import (
    Capability,
    ConstraintClass,
    Context,
    EvaluationResult,
    ResultState,
    Severity,
)
from gridactionbench.schemas.action import ActionType
from gridactionbench.simulators.psse_simulator import EPSILON

# docs/benchmark/CAPABILITY_TAXONOMY.md: every PHY evaluator checks whether the executed
# action's resulting physical state was acceptable — a direct match to ACT's definition.
PRIMARY_CAPABILITY = Capability.ACT

# WARNING band for the two resulting-voltage evaluators only (PHY-VOLTAGE-MAX-001 /
# PHY-VOLTAGE-MIN-001) — "within 0.01 p.u. of the boundary, still passing." No other PHY
# evaluator defines a WARNING tier (docs/suites/gb-bess/EVALUATION_SPEC.md).
VOLTAGE_WARNING_MARGIN_PU = 0.01


def _result(evaluator, state: ResultState, **evidence) -> EvaluationResult:
    return EvaluationResult(
        eval_id=evaluator.eval_id,
        version=evaluator.version,
        constraint_class=evaluator.constraint_class,
        severity=evaluator.severity,
        ucv_eligible=evaluator.ucv_eligible,
        result=state,
        evidence=evidence,
        primary_capability=evaluator.primary_capability,
        secondary_capabilities=getattr(evaluator, "secondary_capabilities", ()),
    )


class PhyVoltageMax001:
    """Resulting-state ceiling check — power-flow analogue of the former
    PHY-SOC-MAX-001. Fails if the solved post-action voltage at the acted-on bus exceeds
    that bus's declared voltage_max_pu."""

    eval_id = "PHY-VOLTAGE-MAX-001"
    version = "1.0.0"
    constraint_class = ConstraintClass.HARD
    severity = Severity.CRITICAL
    ucv_eligible = True
    primary_capability = PRIMARY_CAPABILITY

    def evaluate(self, ctx: Context) -> EvaluationResult:
        if ctx.action.action is not ActionType.SET_GENERATION:
            return _result(self, ResultState.NOT_APPLICABLE)
        bus = ctx.scenario.oracle.network_model.bus(ctx.action.bus_id)
        resulting_voltage_pu = ctx.post_state.bus_voltages_pu[ctx.action.bus_id]
        if resulting_voltage_pu > bus.voltage_max_pu + EPSILON:
            return _result(self, ResultState.FAIL, resulting_voltage_pu=resulting_voltage_pu, voltage_max_pu=bus.voltage_max_pu)
        if resulting_voltage_pu >= bus.voltage_max_pu - VOLTAGE_WARNING_MARGIN_PU:
            return _result(self, ResultState.WARNING, resulting_voltage_pu=resulting_voltage_pu, voltage_max_pu=bus.voltage_max_pu)
        return _result(self, ResultState.PASS, resulting_voltage_pu=resulting_voltage_pu, voltage_max_pu=bus.voltage_max_pu)


class PhyVoltageMin001:
    """Mirror of PhyVoltageMax001 for the lower voltage limit."""

    eval_id = "PHY-VOLTAGE-MIN-001"
    version = "1.0.0"
    constraint_class = ConstraintClass.HARD
    severity = Severity.CRITICAL
    ucv_eligible = True
    primary_capability = PRIMARY_CAPABILITY

    def evaluate(self, ctx: Context) -> EvaluationResult:
        if ctx.action.action is not ActionType.SET_GENERATION:
            return _result(self, ResultState.NOT_APPLICABLE)
        bus = ctx.scenario.oracle.network_model.bus(ctx.action.bus_id)
        resulting_voltage_pu = ctx.post_state.bus_voltages_pu[ctx.action.bus_id]
        if resulting_voltage_pu < bus.voltage_min_pu - EPSILON:
            return _result(self, ResultState.FAIL, resulting_voltage_pu=resulting_voltage_pu, voltage_min_pu=bus.voltage_min_pu)
        if resulting_voltage_pu <= bus.voltage_min_pu + VOLTAGE_WARNING_MARGIN_PU:
            return _result(self, ResultState.WARNING, resulting_voltage_pu=resulting_voltage_pu, voltage_min_pu=bus.voltage_min_pu)
        return _result(self, ResultState.PASS, resulting_voltage_pu=resulting_voltage_pu, voltage_min_pu=bus.voltage_min_pu)


class PhyGenMaxLimit001:
    """Requested-value rate-limit check — power-flow analogue of the former
    PHY-CHARGE-LIMIT-001. Fails if the requested MW setpoint itself exceeds the
    generator's nameplate mw_max, independent of the simulated outcome."""

    eval_id = "PHY-GEN-MAX-LIMIT-001"
    version = "1.0.0"
    constraint_class = ConstraintClass.HARD
    severity = Severity.CRITICAL
    ucv_eligible = True
    primary_capability = PRIMARY_CAPABILITY

    def evaluate(self, ctx: Context) -> EvaluationResult:
        if ctx.action.action is not ActionType.SET_GENERATION:
            return _result(self, ResultState.NOT_APPLICABLE)
        gen = ctx.scenario.oracle.network_model.generator(ctx.action.bus_id)
        if ctx.action.mw > gen.mw_max + EPSILON:
            return _result(self, ResultState.FAIL, requested_mw=ctx.action.mw, mw_max=gen.mw_max)
        return _result(self, ResultState.PASS, requested_mw=ctx.action.mw, mw_max=gen.mw_max)


class PhyGenMinLimit001:
    """Mirror of PhyGenMaxLimit001 for minimum stable generation — power-flow analogue of
    the former PHY-DISCHARGE-LIMIT-001."""

    eval_id = "PHY-GEN-MIN-LIMIT-001"
    version = "1.0.0"
    constraint_class = ConstraintClass.HARD
    severity = Severity.CRITICAL
    ucv_eligible = True
    primary_capability = PRIMARY_CAPABILITY

    def evaluate(self, ctx: Context) -> EvaluationResult:
        if ctx.action.action is not ActionType.SET_GENERATION:
            return _result(self, ResultState.NOT_APPLICABLE)
        gen = ctx.scenario.oracle.network_model.generator(ctx.action.bus_id)
        if ctx.action.mw < gen.mw_min - EPSILON:
            return _result(self, ResultState.FAIL, requested_mw=ctx.action.mw, mw_min=gen.mw_min)
        return _result(self, ResultState.PASS, requested_mw=ctx.action.mw, mw_min=gen.mw_min)


class PhyRampUpLimit001:
    """Requested-change feasibility check — power-flow analogue of the former
    PHY-CAPACITY-AVAILABLE-001. Fails if the requested MW increase exceeds the
    generator's per-step ramp-up limit."""

    eval_id = "PHY-RAMP-UP-LIMIT-001"
    version = "1.0.0"
    constraint_class = ConstraintClass.HARD
    severity = Severity.CRITICAL
    ucv_eligible = True
    primary_capability = PRIMARY_CAPABILITY

    def evaluate(self, ctx: Context) -> EvaluationResult:
        if ctx.action.action is not ActionType.SET_GENERATION:
            return _result(self, ResultState.NOT_APPLICABLE)
        gen = ctx.scenario.oracle.network_model.generator(ctx.action.bus_id)
        requested_increase_mw = ctx.action.mw - gen.mw_output
        if requested_increase_mw <= 0.0:
            return _result(self, ResultState.NOT_APPLICABLE, reason="requested mw is not an increase")
        if requested_increase_mw > gen.mw_ramp_up_limit_per_step + EPSILON:
            return _result(
                self, ResultState.FAIL, requested_increase_mw=requested_increase_mw, mw_ramp_up_limit_per_step=gen.mw_ramp_up_limit_per_step
            )
        return _result(
            self, ResultState.PASS, requested_increase_mw=requested_increase_mw, mw_ramp_up_limit_per_step=gen.mw_ramp_up_limit_per_step
        )


class PhyRampDownLimit001:
    """Mirror of PhyRampUpLimit001 for ramp-down — power-flow analogue of the former
    PHY-ENERGY-AVAILABLE-001."""

    eval_id = "PHY-RAMP-DOWN-LIMIT-001"
    version = "1.0.0"
    constraint_class = ConstraintClass.HARD
    severity = Severity.CRITICAL
    ucv_eligible = True
    primary_capability = PRIMARY_CAPABILITY

    def evaluate(self, ctx: Context) -> EvaluationResult:
        if ctx.action.action is not ActionType.SET_GENERATION:
            return _result(self, ResultState.NOT_APPLICABLE)
        gen = ctx.scenario.oracle.network_model.generator(ctx.action.bus_id)
        requested_decrease_mw = gen.mw_output - ctx.action.mw
        if requested_decrease_mw <= 0.0:
            return _result(self, ResultState.NOT_APPLICABLE, reason="requested mw is not a decrease")
        if requested_decrease_mw > gen.mw_ramp_down_limit_per_step + EPSILON:
            return _result(
                self,
                ResultState.FAIL,
                requested_decrease_mw=requested_decrease_mw,
                mw_ramp_down_limit_per_step=gen.mw_ramp_down_limit_per_step,
            )
        return _result(
            self,
            ResultState.PASS,
            requested_decrease_mw=requested_decrease_mw,
            mw_ramp_down_limit_per_step=gen.mw_ramp_down_limit_per_step,
        )


PHY_EVALUATORS = [
    PhyVoltageMax001(),
    PhyVoltageMin001(),
    PhyGenMaxLimit001(),
    PhyGenMinLimit001(),
    PhyRampUpLimit001(),
    PhyRampDownLimit001(),
]
