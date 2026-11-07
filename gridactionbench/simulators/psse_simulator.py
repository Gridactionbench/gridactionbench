"""PSSESimulatorAdapter — the reference simulator, replacing SimpleBessSimulator.

Implements the frozen conventions in docs/suites/gb-bess/SPECIFICATION.md §9 (power-flow
revision). Orchestrates gridactionbench.simulators.psspy_client; contains no power-flow
math of its own and no knowledge of whether the underlying `psspy` is real PSS/E or a test
double — see psspy_client.py's module docstring for what is and isn't verified.

Simulator version: 1.0.0 (docs/benchmark/VERSIONING.md: MAJOR change from the battery
state-transition model to a PSS/E-backed power-flow model).

Determinism: unlike SimpleBessSimulator's exact closed-form arithmetic, PSS/E's
Newton-Raphson solve is deterministic only to solver tolerance (fixed solve options, fresh
case load per step — see `step()`). docs/testing/TEST_STRATEGY.md's determinism contract is
tolerance-based for this simulator, not bit-exact — an explicit, documented change recorded
in ADR-018, not a silent loosening.
"""

from __future__ import annotations

from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import NetworkModel
from gridactionbench.simulators import psspy_client
from gridactionbench.simulators.base import PowerFlowStepResult

SIMULATOR_VERSION = "1.0.0"

# Floating-point/solver tolerance, fixed by SPECIFICATION.md §9.7. Applied as
# `value <= limit + EPSILON`, never subtracted from the value side.
EPSILON = 1e-6


class PSSESimulatorAdapter:
    """PSS/E-backed power-flow simulator. See module docstring."""

    version = SIMULATOR_VERSION

    def step(
        self,
        network_model: NetworkModel,
        action: AgentActionV1,
        dt_hours: float,
        seed: int | None = None,
    ) -> PowerFlowStepResult:
        """Deterministic to solver tolerance given (network_model, action, dt_hours) —
        see module docstring. `seed`/`dt_hours` are accepted for interface symmetry with
        the prior simulator and forward compatibility with a future stochastic/ramp-limited
        extension; a single power-flow solve is instantaneous (not itself time-integrated)
        in v0.2."""
        del seed, dt_hours  # unused in v0.2 — see docstring

        # Fresh case load every step (never reuse PSS/E's in-memory state across steps) —
        # the deliberate choice that keeps this adapter's determinism contract well-defined
        # despite psspy's own stateful, in-process API (ADR-018).
        psspy_client.load_case(network_model)

        if action.action is ActionType.SET_GENERATION:
            psspy_client.apply_generation_setpoint(action.bus_id, action.mw)

        converged = psspy_client.solve()

        bus_ids = [b.bus_id for b in network_model.buses]
        gen_bus_ids = [g.bus_id for g in network_model.generators]

        generator_outputs_mw = psspy_client.read_generator_outputs(gen_bus_ids)
        return PowerFlowStepResult(
            converged=converged,
            bus_voltages_pu=psspy_client.read_bus_voltages(bus_ids),
            branch_loadings_mva=psspy_client.read_branch_loadings(network_model.branches, generator_outputs_mw),
            generator_outputs_mw=generator_outputs_mw,
        )

    def validate_action(self, network_model: NetworkModel, action: AgentActionV1) -> bool:
        """Cheap pre-check only — see gridactionbench.core.validator.ActionValidator for
        the canonical, evaluator-driven Action Validator that actually gates execution."""
        if action.action is ActionType.SET_GENERATION:
            try:
                gen = network_model.generator(action.bus_id)
            except StopIteration:
                return False
            return gen.mw_min - EPSILON <= action.mw <= gen.mw_max + EPSILON
        return True
