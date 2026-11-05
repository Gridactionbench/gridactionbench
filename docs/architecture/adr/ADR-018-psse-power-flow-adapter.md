# ADR-018: PSS/E Power-Flow Simulator Adapter (supersedes ADR-003)

**Status:** Accepted — supersedes ADR-003-simulator-abstraction.md

## Context
The benchmark's subject system changes from a single Battery Energy Storage System
(SOC, charge/discharge efficiency, import/export headroom) to a small, self-contained,
synthetic power-flow network (buses, branches, one generator), simulated by Siemens PTI
PSS/E via its `psspy` Python API — an explicit direction set by the project owner,
overriding ADR-003's decision to forbid a power-flow solver in v0.1.

Three things make this a defensible pivot rather than an ad hoc reversal, worth recording
honestly alongside the two real risks it introduces:

- **`docs/project/PID.md` already recorded a caution against this exact move** — scaling
  past single-asset scope before the methodology is externally calibrated risks losing
  deterministic-evaluation rigor, since multi-asset/network coordination has genuinely
  ambiguous "correct" actions. That caution is not wrong; it is being consciously
  overridden here at the project owner's direction, not forgotten.
- **The architecture already anticipated a simulator swap.** `docs/architecture/ARCHITECTURE.md`
  names the Harness layer (`core/`, `schemas/`, `simulators/`, `evaluators/base.py`,
  `runners/`, `provenance/`) as reusable scaffolding for "a future second environment," and
  `docs/benchmark/STRESS_DIMENSIONS.md`'s complexity ladder already gestures at "C3: DER +
  grid/network/market interaction." ADR-003 itself reserved the `SimulatorAdapter` seam for
  "a future PyPSA/PandaPower/Grid2Op-backed adapter... without redesign" — PSS/E was not
  named there, but the seam is the same one this ADR uses.
- **Benchmark freeze (Phase 9, `docs/project/PROJECT_PLAN.md`) has not happened.** Every
  scenario is still `review_status: DRAFT`. `docs/benchmark/VERSIONING.md`'s immutability
  rule governs *released* artifacts; nothing released is being silently rewritten here.

## Decision
Replace `SimpleBessSimulator` with `PSSESimulatorAdapter`
(`gridactionbench/simulators/psse_simulator.py`), which implements the existing two-method
`SimulatorAdapter` Protocol unchanged in spirit — `step`/`validate_action` — but against a
power-flow-shaped `NetworkModel` (buses, branches, one generator) instead of a single
`BatteryState`, and a `PowerFlowStepResult` (bus voltages, branch loadings, convergence
flag, generator outputs) instead of `StepResult` (resulting SOC, energy delta).

All `psspy` calls are isolated behind one lazily-imported module,
`gridactionbench/simulators/psspy_client.py` — the only module that imports `psspy`, and
only inside each function body, never at module import time. This keeps `psspy` out of
`pyproject.toml` entirely (a machine with no PSS/E install can still import every other
module in this codebase) and lets tests substitute a fake module via
`sys.modules["psspy"] = ...` before first use. `tests/fakes/fake_psspy.py` is that fake — a
deliberately simplified linear voltage solve, documented as a test double, never claimed to
be a real power-flow solver.

**Scope of what `psspy` actually solves (v1.0):** only bus voltage, via `psseinit` +
per-element data-entry calls + `fnsl` + `busdat`. Branch loading is *not* read from a
`psspy` line-flow call — it is computed directly, in plain Python shared by both the real
and fake code paths, from each branch's own declared `sensitivity_mva_per_mw` (a signed,
offline-study-style distribution factor) applied to the generator's genuinely-solved MW
output. Meaningfully solving real line flows would require a far richer network case
(full topology, loads, reactances) than this benchmark's minimal synthetic model provides;
narrowing to a declared linear sensitivity is a documented simplification, not a silent
one, and it is also what makes the model correctly support a branch that binds on a
*decrease* in generation (negative sensitivity — e.g. an upstream branch covering local
load the generator isn't currently meeting) as well as one that binds on an increase.

**Relationship to ADR-015 (physical-system isolation):** unaffected and still
non-negotiable. PSS/E is used here only as an offline load-flow study engine against a
small, self-contained, synthetic case built in-memory from this benchmark's own
`NetworkModel` — never against a live grid connection or real operational system. Bus and
branch addressing (`bus_id`, `branch_id`) refers only to elements of this loaded synthetic
case, never a real-world device or endpoint; no SCADA/EMS/DERMS client library is, or
becomes, a dependency of `gridactionbench/`.

**Determinism contract — changed, explicitly:** `SimpleBessSimulator`'s closed-form
arithmetic was bit-exact across repeated calls and fresh process reloads
(`docs/testing/TEST_STRATEGY.md`'s prior "exact match" requirement). `PSSESimulatorAdapter`
reloads the case fresh on every `step()` call (never reusing PSS/E's own in-memory state
across steps) specifically so this adapter's determinism remains well-defined despite
`psspy`'s stateful, in-process API — but a real PSS/E Newton-Raphson solve is not
guaranteed bit-identical run over run the way closed-form arithmetic is. This repo's test
suite only ever exercises the fake (itself exact arithmetic, so its own tests still pass
bit-exact), but anyone validating this adapter against a real, licensed PSS/E install
should expect to relax `tests/reproducibility/test_determinism.py`'s equality checks to a
small numerical tolerance for that path, not assume bit-exactness carries over.

**Python/`psspy` version coupling — a real, unresolved risk, stated plainly:** this
repository's floor is Python >=3.11 (`pyproject.toml`), with a 3.13.5 development
environment. `psspy` has historically shipped tied to specific, often older, Python builds
bundled with a given PSS/E release. Isolating all `psspy` calls behind
`psspy_client.py` means the rest of the codebase stays version-agnostic, but real interop
(possibly an out-of-process call to PSS/E's own bundled interpreter, or a PSS/E release
whose documented "Python 3 API" happens to support 3.11+) is something only a licensed
PSS/E installation can confirm — not something verified in this environment or by this
change.

**Honesty note on verification:** the `psspy_client.py` calls were written against PSS/E's
publicly documented API shape (`psseinit`, `bus_data_4`, `branch_data`, `plant_data`,
`machine_data_2`, `machine_chng_2`, `fnsl`, `busdat`, `macdat`) as faithfully as possible
without a licensed PSS/E installation to run them against. They have been exercised only
against the fake double. Real-PSS/E numerical correctness has not been verified and should
not be assumed; anyone relying on this adapter for real results must validate it against
their own licensed PSS/E install first.

## Alternatives considered
- **Keep `SimpleBessSimulator`, add a second, parallel PSS/E-backed suite** — rejected at
  the project owner's explicit direction: the subject system is changing, not expanding;
  see the in-place-replacement discussion above for why that doesn't violate this project's
  own versioning discipline given the pre-freeze state.
- **A deterministic power-flow surrogate instead of real `psspy`** — rejected: the explicit
  request was real PSS/E integration, matching ADR-003's own "future adapters" framing of
  a *real* external tool, not another in-house closed-form approximation.
- **Solve branch flow via a real `psspy` line-flow call (`brnmsc`) instead of a declared
  linear sensitivity** — rejected for v1.0: this benchmark's minimal 2-bus-per-scenario case
  has no meaningful topology for a line-flow solve to reflect; a declared sensitivity is
  both simpler and (uniquely) able to represent a decrease-binding branch, which an
  absolute per-generator proportionality constant could not.

## Consequences
- Positive: the `SimulatorAdapter`/`Evaluator`/`Evaluation Engine`/`Decision Record`
  architecture (already documented as domain-agnostic Harness scaffolding) is reused
  unchanged in kind — only the data shapes behind it changed, exactly as ADR-003 and
  `ARCHITECTURE.md` anticipated a future adapter would.
- Positive: `economics.py`'s best-case-value computation, evaluator logic, and baseline
  agents all gained a legitimate real-world analogue this pivot exposed — e.g. per-branch
  signed distribution factors and generator ramp-up/down limits are standard, realistic
  power-system concepts, not inventions forced to fit a battery-shaped benchmark.
- Negative: `core/economics.py`'s "best-case boundary value" lost its exact closed-form
  battery-SOC-inversion computation; the power-flow replacement is a documented
  simplification (exactly one agent-controllable generator considered), not a genuine
  optimal-power-flow solve — see that module's own docstring.
- Negative: real-PSS/E correctness is unverified (see Honesty note above) and the
  Python/`psspy` version-coupling risk is unresolved — both are stated here rather than
  hidden, consistent with this project's existing documentation discipline (e.g. the
  `SimpleBessSimulator` fidelity disclosure ADR-003 itself required).
- Negative: `docs/project/PID.md`'s calibration-before-scaling caution is overridden, not
  satisfied — any future external review of this benchmark should be told this happened
  and why, not discover it by diffing the codebase against that document.
