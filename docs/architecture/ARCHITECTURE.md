# Architecture

**Status:** Revised — September 2026 strategic realignment adds the "Environment/Harness vs. Benchmark" section below, made explicit per that pass's requirement; the rest of this document (package layout, interfaces, everything from Phase 1 implementation) is unchanged.

## Environment/Harness vs. Benchmark (added — September 2026 strategic realignment)

These are two distinct things, and this codebase has always implemented both without previously naming the boundary between them:

**Environment / Harness** — the reusable system that initialises world state, exposes observations, mediates any tools, accepts actions, advances simulation, records trajectories, and runs evaluators. In this codebase: `gridactionbench/core/`, `schemas/`, `simulators/`, `evaluators/base.py`, `runners/`, `provenance/` — none of this is specific to GB-BESS's particular constants or scenario content, and (per `docs/architecture/adr/ADR-002-package-architecture.md`) is explicitly the part of the codebase a future second environment (GB-DER, `docs/project/PID.md` §2.3) would reuse without modification, if its interfaces hold up as intended.

**Benchmark** — a frozen, repeatable evaluation protocol built on the environment: canonical task families, task distributions, public/private instances, fixed evaluation rules, metrics, baseline agents, a repeated-run protocol where necessary, a reporting format, and versioning. In this codebase: `gridactionbench/evaluators/gb_bess/` (concrete evaluator instances), `gridactionbench/scenarios/gb_bess/`, `suites/gb_bess/v0_1/`, `baselines/`, and everything in `docs/suites/gb-bess/` and `docs/benchmark/` that names GB-BESS-specific constraints, thresholds, or scenario content.

**A runnable environment alone is not a benchmark.** `gridactionbench/`'s core package being fully functional does not by itself constitute a released, comparable benchmark — that requires the frozen protocol elements above, which is exactly why `docs/project/DEFINITION_OF_DONE.md`'s five gates exist as a separate concept from "does the code run."

## Component pipeline

```text
Scenario --> Oracle --> Observation --> Agent --> Action Validator --> Simulator
   --> Evaluation --> Counterfactual Analysis (selected scenarios) --> Decision Record --> Report
```

This mirrors `docs/benchmark/SPECIFICATION.md` §1 exactly; this document describes how each stage maps to a package under `gridactionbench/`.

## Package layout (target, per master brief §65)

```text
gridactionbench/
├── core/         # Scenario, Oracle, DecisionRecord data model classes; run orchestration
├── schemas/       # EnergyObservationV1, AgentActionV1 — versioned, validated schema definitions
├── simulators/    # SimulatorAdapter interface + PSSESimulatorAdapter implementation (psspy_client.py isolates the psspy import)
├── evaluators/    # Evaluator interface + one module per catalogue entry (PHY, NET, OPS, DATA, ADV, HUM)
├── scenarios/     # scenario loading, validation, and (Phase 3) template-based generation
├── agents/        # AgentAdapter interface + reference agents (AlwaysIdle, AlwaysEscalate, RuleBased, LLMStructured) + seeded failure agents
├── runners/       # single-step and episode execution orchestration
├── reporting/     # per-dimension scoring, UCV computation, report rendering (docs/benchmark/SCORING.md)
└── provenance/     # git commit, environment, seed capture for Decision Records
```

## Key interfaces

### `SimulatorAdapter`

The simulator boundary is an interface, not a concrete class reference, from day one — see `docs/architecture/adr/ADR-018-psse-power-flow-adapter.md` (supersedes `docs/architecture/adr/ADR-003-simulator-abstraction.md`). `PSSESimulatorAdapter` (backed by Siemens PTI PSS/E's `psspy` API) is the implementation shipped since v0.2, replacing v0.1's `SimpleBessSimulator` — exactly the kind of swap the interface was reserved for, without redesigning the benchmark core.

```text
SimulatorAdapter:
  step(pre_state, action) -> post_state       # deterministic given (pre_state, action, seed)
  validate_action(pre_state, action) -> ValidationResult   # hard-constraint pre-check (see Action Validator, below)
```

### `AgentAdapter`

Provider-neutral boundary between the benchmark runner and any agent implementation — LLM-backed, rule-based, or otherwise. No provider (OpenAI, Anthropic, Google, etc.) is hard-wired into the core runner; provider-specific adapters are optional, separately maintained implementations of this interface (master brief §26).

```text
AgentAdapter:
  act(observation: EnergyObservationV1) -> AgentActionV1
```

### `Evaluator`

Every evaluator in `docs/suites/gb-bess/EVALUATION_SPEC.md` implements a common interface so the reporting layer can aggregate results uniformly regardless of scenario family.

```text
Evaluator:
  eval_id, version, category, criticality   # static metadata, matches the catalogue spec
  evaluate(pre_state, action, post_state, oracle, observation) -> EvaluationResult (pass|warning|failure, evidence)
```

### Action Validator vs. Simulator — a deliberate separation

The Action Validator rejects hard-constraint-violating actions *before* they reach the simulator; the simulator itself never receives or silently clamps an invalid action (see `docs/suites/gb-bess/SPECIFICATION.md` §9). This means: an invalid action always produces an explicit `EvaluationResult: failure` from the relevant evaluator, and the simulator's own state-transition logic can assume its input action is valid, keeping simulator code simple and its correctness easier to test in isolation (Phase 1 golden tests target the validator and simulator separately for exactly this reason).

## Oracle / Observation separation

Implemented as two distinct data structures produced from the same `Scenario` definition: `Oracle` (full ground truth, visible only to the Evaluation Engine and to scenario-authoring/validation tooling) and `EnergyObservationV1` (the subset/possibly-corrupted view exposed to the `AgentAdapter`). A scenario file (`docs/suites/gb-bess/SCENARIO_CATALOGUE.md` shows the YAML shape) declares both explicitly — the Observation is never mechanically derived from the Oracle by a generic "hide some fields" rule, because DATA-family scenarios specifically need the freedom to make the Observation *wrong*, not merely incomplete (master brief §9).

## Decision Record generation

Every runner invocation (single-step or per-episode-step) assembles one immutable Decision Record (schema in `docs/benchmark/SPECIFICATION.md` §7) as its final act, written to portable JSONL. The `provenance/` package is responsible for populating the reproducibility-critical fields (git commit, seed, environment) so no other package needs to duplicate that logic.

## Episode runner

Mode B (`docs/benchmark/SPECIFICATION.md` §2) is implemented as a thin loop over the Mode A single-step pipeline: `State(t) -> Agent -> Action(t) -> Simulator -> State(t+1)` repeated, with the loop itself responsible for detecting and reporting episode-level behavioural metrics (boundary-margin trend, escalation discrimination across steps — see `docs/suites/gb-bess/SCENARIO_CATALOGUE.md`, episode `failure_signature` fields) that have no meaning at the single-step level. The runner does not require a structurally different core pipeline for episodes — this is intentional (master brief §4: "the architecture must support episodes").

## Reporting layer

Implements `docs/benchmark/SCORING.md`'s per-dimension, non-aggregated reporting format directly from a set of Decision Records — the reporting layer never re-derives evaluation verdicts; it only aggregates and presents verdicts already recorded in the Decision Records it reads. This keeps evaluation logic (which must be trustworthy) separate from presentation logic (which can iterate freely without risk to scoring integrity).

## What is explicitly out of the architecture

No component in this architecture issues commands to, or reads live telemetry from, any real energy asset or operational system — see `docs/architecture/SECURITY.md` for the hard isolation guarantee this architecture is designed to make structurally true, not merely policy-true.
