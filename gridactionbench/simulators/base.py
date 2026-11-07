"""SimulatorAdapter interface. See docs/architecture/adr/ADR-018-psse-power-flow-adapter.md
(supersedes docs/architecture/adr/ADR-003-simulator-abstraction.md).

Exactly two methods, by design — no simulator implementation may add a physical-asset
addressing capability to this interface (docs/architecture/SECURITY.md, ADR-015).
`NetworkModel` addressing (`bus_id`, `branch_id`) refers only to elements of a loaded
synthetic benchmark case, never a real-world endpoint — ADR-015's constraint is about real
operational systems and is unaffected by this interface's data shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from gridactionbench.schemas.action import AgentActionV1
from gridactionbench.schemas.observation import NetworkModel


@dataclass(frozen=True)
class PowerFlowStepResult:
    """Result of one deterministic (to solver tolerance) power-flow solve.

    Exposed as per-bus/per-branch/per-generator dicts (not just a pass/fail verdict) so
    property tests can assert power-balance and limit invariants directly — see
    docs/suites/gb-bess/SPECIFICATION.md §9, docs/testing/TEST_STRATEGY.md.
    """

    converged: bool
    bus_voltages_pu: dict[int, float] = field(default_factory=dict)
    branch_loadings_mva: dict[str, float] = field(default_factory=dict)
    generator_outputs_mw: dict[int, float] = field(default_factory=dict)


class SimulatorAdapter(Protocol):
    def step(
        self,
        network_model: NetworkModel,
        action: AgentActionV1,
        dt_hours: float,
        seed: int | None = None,
    ) -> PowerFlowStepResult: ...

    def validate_action(self, network_model: NetworkModel, action: AgentActionV1) -> bool:
        """Hard-constraint pre-check only — see gridactionbench.core.validator for the
        Action Validator that actually gates simulator execution. This method exists on
        the interface for adapters that want to expose a cheap validity pre-check; the
        canonical, evaluator-driven check lives in the Action Validator, not here."""
        ...
