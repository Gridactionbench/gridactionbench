"""Thin wrapper around Siemens PTI PSS/E's `psspy` Python API.

This is the **only** module in this codebase that imports `psspy`, and it does so lazily
(inside each function, not at module import time) so that:

  1. the rest of the codebase stays importable on a machine with no PSS/E installation at
     all (`psspy` is not, and must never become, a dependency of `pyproject.toml`);
  2. tests can substitute a fake module via `sys.modules["psspy"] = <fake>` *before* any
     function here is first called, without needing to patch every call site individually.

**Honesty note (see docs/architecture/adr/ADR-018-psse-power-flow-adapter.md):** the calls
below are written against PSS/E's publicly documented `psspy` API shape (`psseinit`,
`bus_data_4`, `branch_data`, `plant_data`, `machine_data_2`, `fnsl`, `busdat`, `brnflo`,
`macdat`) as faithfully as this project's authors could without a licensed PSS/E
installation to run them against. **They have not been executed against real PSS/E.**
Anyone relying on this adapter for real results must validate it against their own licensed
PSS/E install before trusting its output; this module's test coverage uses a fake `psspy`
double (`tests/fakes/fake_psspy.py`), which proves this client calls a *plausible* API
shape and handles results correctly, not that real PSS/E accepts these exact calls.

PSS/E is only ever used here as an offline load-flow study engine against a small,
self-contained, synthetic case built in-memory from this benchmark's own `NetworkModel` —
never against a live grid connection or real operational system
(docs/architecture/adr/ADR-015-physical-system-isolation.md).

**Scope note:** `psspy`'s solve (`fnsl`) is used to determine bus voltages — a genuine
AC power-flow result. Branch loading is deliberately *not* read from a `psspy` line-flow
call; see `read_branch_loadings`'s docstring for why and what is computed instead.
"""

from __future__ import annotations

from types import ModuleType

from gridactionbench.schemas.observation import NetworkModel

# PSS/E's own convention: 0 means "no error" on most psspy calls.
_PSSPY_OK = 0


class PsseSolveError(RuntimeError):
    """Raised when PSS/E case setup or the power-flow solve itself fails."""


def _get_psspy() -> ModuleType:
    try:
        import psspy  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PsseSolveError(
            "psspy is not importable — no PSS/E installation found on this machine. "
            "Real power-flow simulation requires a licensed PSS/E install with its "
            "Python API on the interpreter path; see ADR-018 for the known Python-version "
            "coupling risk this implies."
        ) from exc
    return psspy


def load_case(network_model: NetworkModel) -> None:
    """Build an in-memory PSS/E case from this scenario's NetworkModel.

    Uses `psseinit` + per-element `bus_data_4`/`branch_data`/`plant_data`/`machine_data_2`
    calls rather than loading an external .sav/.raw file, so every scenario's case is fully
    defined by its own YAML — no external case-file dependency to keep in sync.
    """
    psspy = _get_psspy()

    ierr = psspy.psseinit(max(50, len(network_model.buses) + 10))
    if ierr != _PSSPY_OK:
        raise PsseSolveError(f"psseinit failed (ierr={ierr})")

    for bus in network_model.buses:
        # bus_data_4(ibus, inode, intgar, realar, name) — intgar[0]=bus type (1=load/PQ,
        # 2=generator/PV, 3=slack); realar[1]=voltage setpoint/estimate (p.u.).
        bus_type = 3 if bus.bus_id == network_model.buses[0].bus_id else 2
        ierr = psspy.bus_data_4(
            bus.bus_id,
            0,
            [bus_type, 1, 1, 1],
            [0.0, bus.voltage_pu, 0.0, 0.0, 1.1, 0.9],
        )
        if ierr != _PSSPY_OK:
            raise PsseSolveError(f"bus_data_4 failed for bus {bus.bus_id} (ierr={ierr})")

    for branch in network_model.branches:
        # branch_data(ibus, jbus, ickt, intgar, realar) — realar carries R/X/B and the
        # MVA rating used as this branch's thermal limit.
        ierr = psspy.branch_data(
            branch.from_bus,
            branch.to_bus,
            branch.branch_id,
            [1, 1, 1, 1, 1, 0],
            [0.01, 0.1, 0.0, branch.mva_limit, branch.mva_limit, branch.mva_limit, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        if ierr != _PSSPY_OK:
            raise PsseSolveError(
                f"branch_data failed for branch {branch.branch_id} (ierr={ierr})"
            )

    for gen in network_model.generators:
        ierr = psspy.plant_data(gen.bus_id, 0, [0, 0])
        if ierr != _PSSPY_OK:
            raise PsseSolveError(f"plant_data failed for bus {gen.bus_id} (ierr={ierr})")
        # machine_data_2(ibus, id, intgar, realar) — realar[0]=PGEN (MW), realar[2]=PMAX,
        # realar[3]=PMIN.
        ierr = psspy.machine_data_2(
            gen.bus_id,
            "1",
            [1, 0, 0, 0, 0, 0],
            [gen.mw_output, 0.0, gen.mw_max, gen.mw_min, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        if ierr != _PSSPY_OK:
            raise PsseSolveError(f"machine_data_2 failed for bus {gen.bus_id} (ierr={ierr})")


def apply_generation_setpoint(bus_id: int, mw: float) -> None:
    """Change one machine's requested MW output ahead of the next solve."""
    psspy = _get_psspy()
    ierr = psspy.machine_chng_2(bus_id, "1", [], [mw, -999.0])
    if ierr != _PSSPY_OK:
        raise PsseSolveError(f"machine_chng_2 failed for bus {bus_id} (ierr={ierr})")


def solve() -> bool:
    """Run PSS/E's full Newton-Raphson power-flow solution (`fnsl`). Returns True if the
    case converged."""
    psspy = _get_psspy()
    ierr = psspy.fnsl([0, 0, 0, 1, 1, 0, 99, 0])
    # API success alone must not be treated as numerical convergence.
    return ierr == _PSSPY_OK and psspy.solved() == _PSSPY_OK


def read_bus_voltages(bus_ids: list[int]) -> dict[int, float]:
    psspy = _get_psspy()
    result: dict[int, float] = {}
    for bus_id in bus_ids:
        ierr, voltage_pu = psspy.busdat(bus_id, "PU")
        if ierr != _PSSPY_OK:
            raise PsseSolveError(f"busdat failed for bus {bus_id} (ierr={ierr})")
        result[bus_id] = voltage_pu
    return result


def read_branch_loadings(branches: list, generator_outputs_mw: dict[int, float]) -> dict[str, float]:
    """Branch loading is **not** read from a `psspy` line-flow call in this v1.0 adapter —
    see the module docstring's honesty note. Meaningfully solving line flows would require
    a far richer network case (full topology, loads, reactances) than this benchmark's
    minimal synthetic 2-bus-per-scenario model provides. Instead, each branch's loading is
    computed directly from its own declared `sensitivity_mva_per_mw` (a signed,
    offline-study-style distribution factor — docs/architecture/adr/ADR-018) applied to
    the generator's genuinely-solved MW output: `mva_flow = branch.baseline_mva +
    branch.sensitivity_mva_per_mw * generator_output_mw`. This is plain Python arithmetic,
    identical for real PSS/E and the fake test double, and correctly supports a branch
    that binds on a *decrease* in generation (negative sensitivity, e.g. an upstream
    branch covering local load the generator isn't currently meeting) as well as one that
    binds on an increase (positive sensitivity) — something a single hardcoded
    proportionality constant could not. `branches` is the scenario's
    `NetworkModel.branches` list.
    """
    result: dict[str, float] = {}
    for branch in branches:
        connected_mw = generator_outputs_mw.get(branch.from_bus, generator_outputs_mw.get(branch.to_bus, 0.0))
        result[branch.branch_id] = branch.baseline_mva + branch.sensitivity_mva_per_mw * connected_mw
    return result


def read_generator_outputs(bus_ids: list[int]) -> dict[int, float]:
    psspy = _get_psspy()
    result: dict[int, float] = {}
    for bus_id in bus_ids:
        ierr, mw_output = psspy.macdat(bus_id, "1", "P")
        if ierr != _PSSPY_OK:
            raise PsseSolveError(f"macdat failed for bus {bus_id} (ierr={ierr})")
        result[bus_id] = mw_output
    return result
