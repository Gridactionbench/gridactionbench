# Domain Model

**Status:** Revised — September 2026 strategic realignment. This document's entities (below) are the GB-BESS-specific instantiation of the general Task/Task Family/Instance/Trial/Trajectory/Outcome/Grader ontology now defined in `docs/benchmark/TASK_MODEL.md` — read that document first for the general model, then this one for how GB-BESS's concrete classes (`Scenario`, `DecisionRecord`, `Evaluator`) map onto it. No entity below is renamed or changed by this pass; `docs/benchmark/TASK_MODEL.md`'s "Terminology mapping" table gives the term-for-term correspondence.

See `docs/architecture/DATA_MODEL.md` for concrete schema field types and `docs/benchmark/SPECIFICATION.md` for the methodology these concepts support.

## Core entities

```text
Scenario
  - identity: scenario_id, scenario_version, suite, suite_version, family
  - Oracle (ground truth)
  - ObservationSpec (what the Agent sees, possibly ≠ Oracle)
  - Constraints: HardConstraint[], OperationalConstraint[]
  - Objectives: Objective[]
  - InformationRequirements: InformationRequirement[]
  - permitted_actions, prohibited_actions, preferred_actions
  - escalation: {required, permitted}
  - provenance: source_type, author, created_date, review_status

Oracle
  - full ground-truth system state at scenario start (and, for episodes, at every step)
  - not visible to the Agent; visible to the Evaluation Engine

EnergyObservationV1 (Observation)
  - the Agent-visible view, generated per ObservationSpec from a Scenario
  - may be a strict subset of the Oracle (information withheld) or may
    deliberately differ from it (information corrupted/stale/conflicting) —
    both are valid ObservationSpec outcomes, not error states

Agent
  - anything implementing the AgentAdapter interface (docs/architecture/ARCHITECTURE.md)
  - produces exactly one AgentActionV1 per Observation it receives

AgentActionV1 (Action)
  - action: SET_GENERATION | IDLE | ESCALATE
  - bus_id, mw, reason_code, confidence, optional_explanation

Action Validator
  - rejects hard-constraint-violating actions before Simulator execution
  - is not itself a scoring evaluator — it protects the Simulator's invariants

Simulator (SimulatorAdapter)
  - deterministic state transition: (pre_state, valid_action, seed) -> post_state

Evaluator
  - one per catalogue entry in docs/suites/gb-bess/EVALUATION_SPEC.md
  - consumes (pre_state, action, post_state, Oracle, Observation)
  - produces an EvaluationResult: pass | warning | failure, plus evidence

Evaluation Engine
  - orchestrates all Evaluators relevant to a Scenario
  - computes derived events: UCV (gated on each evaluator's explicit `ucv_eligible` flag, not on
    severity alone — docs/suites/gb-bess/EVALUATION_SPEC.md), Self-Reported High-Confidence UCV
    (docs/benchmark/SPECIFICATION.md §8)
  - computes counterfactual results where the Scenario specifies them

Decision Record
  - the immutable, complete record of one Scenario x Agent execution
  - schema: docs/benchmark/SPECIFICATION.md §7

Run
  - a set of Decision Records produced under one fixed configuration
  - the unit a Report is generated from
```

## Relationships

- A **Scenario** has exactly one **Oracle** (per timestep, for episodes) and exactly one **ObservationSpec** describing how to derive the Agent-visible Observation from that Oracle.
- An **Agent** is evaluated against many Scenarios to produce a **Run**; the same Agent configuration run against the same Scenario set with a different random seed (for stochastic agents) produces a distinct Run, not an overwrite of the prior one (master brief §54).
- An **Evaluator** belongs to exactly one scenario family category (PHY/NET/OPS/MKT/DATA/ADV/HUM) for reporting-dimension purposes, but may be listed as `relevant_evaluators` on Scenarios from a different nominal family when cross-cutting (e.g. `NET-BRANCH-THERMAL-LIMIT-001` is listed as relevant on `GB-BESS-DATA-017`, a DATA-family scenario, because the DATA failure mode there has a NET-family consequence).
- A **UCV** is not a distinct database entity — it is a derived boolean computed from an evaluator's `ucv_eligible: true` classification (`docs/suites/gb-bess/EVALUATION_SPEC.md` — **not** simply `severity: CRITICAL`, corrected Phase 0.5) failing in combination with the Agent's Action not including an ESCALATE and not otherwise indicating recognition of the issue (see `docs/benchmark/SPECIFICATION.md` §8). It is computed and stored on the Decision Record at Evaluation Engine time so reporting never needs to recompute it from raw evaluator results.

## Four-way constraint/objective/information taxonomy (recap)

See `docs/benchmark/SPECIFICATION.md` §3 for the full definitions of Hard Constraints, Operational Constraints, Objectives, and Information Requirements — this domain model treats all four as first-class, independently-typed entities attached to a Scenario, never conflated into a single generic "rule" type. This typing decision is what lets `docs/benchmark/SCORING.md` report physical, network, operational-policy, and data-quality adherence as genuinely separate dimensions rather than derived post-hoc from an untyped rule list.

## Episode-specific extensions

For Mode B, `Oracle` and `Observation` become time-indexed (`Oracle(t)`, `Observation(t)`), and a `Scenario` used in episode mode additionally carries an `EpisodeSpec` (step count, per-step Oracle deltas, `failure_signature` — see `docs/suites/gb-bess/SCENARIO_CATALOGUE.md` episode entries for the concrete shape). `Decision Record`s are still generated one-per-step (not one-per-episode), and an Episode Report aggregates the per-step Decision Records plus the episode-level behavioural metrics that only make sense across the sequence (`docs/architecture/ARCHITECTURE.md`, "Episode runner").
