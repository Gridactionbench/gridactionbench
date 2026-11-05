# Benchmark Card — GridActionBench

**Benchmark:** GridActionBench
**First environment:** GB-BESS v0.2 (draft, unreleased)
**Status:** Phase 0-3 specification, research, and initial implementation; revised by the PSS/E power-flow pivot (`docs/architecture/adr/ADR-018-psse-power-flow-adapter.md`); no released results yet
**Last updated:** 2026-11-05

This card follows the spirit of model/dataset cards (e.g., Mitchell et al., "Model Cards for Model Reporting"; Gebru et al., "Datasheets for Datasets") applied to a benchmark rather than a model or dataset.

---

## Mission

**GridActionBench is an open benchmark for evaluating the reliability boundaries of autonomous AI agents acting in dynamic energy systems.** It measures how different agent architectures perceive, decide, act, adapt, and escalate as system complexity, operational uncertainty, and autonomy burden increase. Initially grounded in the Great Britain electricity system, GridActionBench combines executable energy environments, reproducible scenarios, consequential actions, and deterministic evaluation to identify where autonomous behaviour remains reliable and where it begins to fail. See `docs/benchmark/RELIABILITY_BOUNDARY_MODEL.md` for the formal statement.

GridActionBench does not claim to be the first energy-agent benchmark, the first executable energy benchmark, the first long-horizon energy-agent benchmark, or the first dynamic power-system AI benchmark — see `docs/research/DESIGN_EVIDENCE_BASE.md` for how prior research is used as evidence for specific design choices rather than as a novelty claim. The defensible position: GridActionBench focuses specifically on measuring the reliability boundaries of autonomous agent architectures as operational burden increases, initially within a rigorously GB-grounded energy-system context.

## Purpose of the first environment, GB-BESS v0.2

GridActionBench evaluates whether an AI agent (or any decision-making system — LLM agent, rule-based controller, optimizer, RL policy, hybrid, tool-using agent) **selects a valid and appropriate operational action** given what it knows, what it does not know, the constraints governing the system, and the consequences of that action. The governing principle: *do not just evaluate what an AI says — evaluate what happens if you let it act.*

The first environment, **GB-BESS v0.2**, applies this to dispatch decisions for a small, synthetic power-flow network (one slack bus, one generator bus, one connecting branch) simulated by Siemens PTI PSS/E, in a Great Britain electricity-system context — the first, deliberately narrow rung (C0, `docs/benchmark/STRESS_DIMENSIONS.md`) of a named future complexity progression, not the permanent boundary of what GridActionBench evaluates. v0.1 modeled a single Battery Energy Storage System instead; see `docs/architecture/adr/ADR-018-psse-power-flow-adapter.md` for why and how that changed. See `docs/project/PID.md` §2.3 for the complexity progression and the explicit non-commitment framing around it.

## Intended users

- Researchers studying AI agent reliability in consequential, constrained decision domains.
- Teams building AI-assisted or autonomous energy operations tooling, who want independent evidence of failure modes before deployment.
- Policy and assurance researchers (e.g., studying staged autonomy or assurance frameworks) who need empirical behavioural evidence rather than capability-only benchmarks.
- Benchmark methodology researchers interested in action-validity, information-sufficiency, and consequence-based evaluation as a category distinct from answer-quality evaluation.

## Intended use

- Comparing how different agent architectures behave under identical, versioned physical, network, operational-policy, market, information-quality, and adversarial conditions.
- Discovering constraint violations, escalation failures, and information-sufficiency failures in a controlled, reproducible, simulation-only environment.
- Producing evidence for research and policy discussion about AI agent reliability in energy operations (see `docs/project/PID.md` for the intended DESNZ evidence output).

## Out-of-scope use

- **Certification of any real AI system as safe for real-world energy operations.** GridActionBench is a behavioural research benchmark, not a certification, conformance, or regulatory-approval system.
- **Any live or physical control of a real energy asset.** GB-BESS v0.2 is simulation-only by hard architectural constraint (see `docs/architecture/SECURITY.md`) — PSS/E is used strictly as an offline load-flow study engine against a synthetic, self-contained case, never a live grid connection (`docs/architecture/adr/ADR-018-psse-power-flow-adapter.md`).
- **Claiming government or regulatory endorsement.** GridActionBench is not an official UK government benchmark, is not endorsed by DESNZ, Ofgem, NESO, or Elexon, and does not claim to be.
- **Ranking foundation models as a leaderboard exercise.** GridActionBench does not assume an LLM is the correct architecture for this task; a deterministic controller outperforming an LLM agent is a valid, expected, and reportable research outcome, not a benchmark failure.
- **Complete Grid Code / Distribution Code compliance assessment.** GB-BESS v0.2 models a deliberately narrow subset of physical and operational constraints; it does not implement full regulatory compliance testing.

## Subject

Individual dispatch decisions (SET_GENERATION / IDLE / ESCALATE) for one controllable generator in a small, synthetic power-flow network, evaluated at a single decision point (Mode A, primary) or across a short sequence of decision points (Mode B, small validated subset).

## Geography

Great Britain electricity-system context. See `docs/suites/gb-bess/GB_SPECIFICITY.md` for an evidenced breakdown of exactly which design elements are genuinely GB-specific versus generic, and `docs/suites/gb-bess/GB_CONTEXT.md` for institutional background.

## Research questions

Primary: *How reliably do different AI-agent architectures make power-flow dispatch decisions under physical constraints, network constraints, operational policies, market signals, degraded information, and adversarial conditions relevant to Great Britain?*

Secondary questions this benchmark is designed to surface evidence for (not exhaustive — see `docs/project/PID.md`):
- Which constraint categories (physical / network / operational-policy) are violated most often, and by which agent architectures?
- Do agents recognize insufficient information, or act on stale/missing/contradictory data as if it were reliable?
- Do agents escalate appropriately — neither over-escalating into operational uselessness nor under-escalating into unrecognised critical violations?
- Do economic incentives (price signals) cause agents to violate constraints they would otherwise respect?
- How do agents respond to adversarial inputs attempting to override stated constraints?
- Do failure patterns persist or worsen over a sequence of decisions (episode mode)?

## Benchmark modes

- **Mode A — Single-Step Evaluation** (primary): one observation, one action, one evaluation.
- **Mode B — Episode Evaluation** (small validated subset): a short sequence of decision points, used to detect behaviour that only emerges over time (progressive output depletion toward a reserve margin, repeated unnecessary escalation, oscillation, etc.).

## Scenario taxonomy

Seven families: **PHY** (physical constraints), **NET** (network constraints), **OPS** (operational policy), **MKT** (economic objectives), **DATA** (information quality), **ADV** (adversarial conditions), **HUM** (human escalation). See `docs/suites/gb-bess/SCENARIO_CATALOGUE.md`.

## Data

Synthetic scenarios calibrated to plausible GB parameter ranges, informed by (but not currently built from) real GB institutional mechanisms and, where licence-confirmed, real GB market data in later phases. See `docs/data/DATA_SOURCES.md` and `docs/data/DATA_PROVENANCE.md`. No scenario is represented as a historical GB event unless explicitly and verifiably sourced as such.

## Simulator

`PSSESimulatorAdapter` — backed by Siemens PTI PSS/E via its `psspy` Python API, solving bus voltage genuinely (Newton-Raphson, via `fnsl`) for a small, self-contained, synthetic 2-bus network per scenario. Branch loading is deliberately *not* read from a PSS/E line-flow call — it is computed from each branch's own declared linear sensitivity, in plain Python (see `docs/architecture/adr/ADR-018-psse-power-flow-adapter.md` for why, and for the honest limitations this carries: real-PSS/E numerical correctness has not been verified in this project's own environment, and a Python/`psspy` version-compatibility risk is unresolved). Supersedes v0.1's `SimpleBessSimulator` (a battery state-transition model; see `docs/architecture/adr/ADR-003-simulator-abstraction.md`, now superseded).

## Metrics

Reported as independent dimensions, never collapsed into a single opaque score (see `docs/benchmark/SCORING.md`): physical constraint adherence, network constraint adherence, operational-policy adherence, data-quality handling, adversarial resilience, appropriate escalation rate, unnecessary escalation rate, economic decision quality, and Unrecognised Critical Violation (UCV) counts (absolute, always reported alongside any percentage).

## Validation status (as of this card's last-updated date)

**Pre-calibration.** No golden tests, evaluator validation, scenario validation, or domain-expert review have yet been completed — this Benchmark Card is being published as part of Phase 0 specification work, ahead of any implementation. It will be revised substantially once Phase 1 (technical spike) and Phase 4 (calibration) are complete. Treat all metric names and scenario counts in this document as *design targets*, not validated capabilities, until `docs/project/DEFINITION_OF_DONE.md` is satisfied.

## Known limitations (stated plainly, per HELM's precedent — see `docs/research/PRIOR_ART.md`)

- GB-BESS v0.2 models a single controllable generator in a minimal 2-bus network in isolation, not a multi-asset or whole-grid system — this is documented as the first rung (C0) of a named complexity progression (`docs/benchmark/STRESS_DIMENSIONS.md`), not a claim that single-asset evaluation is sufficient on its own.
- The ADAPT capability (`docs/benchmark/CAPABILITY_TAXONOMY.md`) is thinly represented — most existing episodes test policy or telemetry change, none test a failed tool call.
- Branch loading is a declared-linear-sensitivity computation, not a genuine PSS/E line-flow solve — a documented simplification, not a hidden one (`docs/architecture/adr/ADR-018-psse-power-flow-adapter.md`).
- Real-PSS/E numerical correctness is unverified: this project's own environment has no licensed PSS/E install, so `psspy_client.py` has been exercised only against a fake test double (`tests/fakes/fake_psspy.py`), and a Python/`psspy` version-compatibility risk is unresolved.
- Economic modeling is a narrow scalar reference-price signal considering exactly one agent-controllable generator, not a full revenue-stacking or optimal-power-flow model.
- GB specificity is currently contextual/structural, not yet data-grounded in licence-confirmed real GB market data (see `docs/suites/gb-bess/GB_SPECIFICITY.md`, "Honest self-assessment").
- The benchmark cannot and does not certify real-world safety; see `docs/benchmark/METHODOLOGY.md` for the project's terminology discipline around "unsafe" vs. "constraint violation."
- Public benchmark data will, over time, likely appear in model-training corpora; see `docs/benchmark/CONTAMINATION_POLICY.md`.
- This benchmark is incomplete by design and cannot represent every real-world power-system operating condition.

## Misuse risks

- Treating a high GB-BESS score as evidence of real-world operational safety or regulatory readiness.
- Treating GB-BESS as a general AI capability leaderboard rather than a behavioural-reliability research tool.
- Assuming public benchmark scenarios remain a valid contamination-free test indefinitely (see `docs/benchmark/CONTAMINATION_POLICY.md`).

## Contamination risks

Public scenarios, once published, may enter model-training data over time. Mitigations include private holdouts, parameterized/generated scenario variants, and scenario retirement; see `docs/benchmark/CONTAMINATION_POLICY.md`. This benchmark does not claim its public test data remains uncontaminated forever.

## Version

GridActionBench framework: unreleased (Phase 0). GB-BESS suite: v0.2 (draft, unreleased). This card will be re-issued at each frozen benchmark version per `docs/benchmark/VERSIONING.md`.

## Governance

See `GOVERNANCE.md` (repository root, once populated) for maintainer, domain reviewer, benchmark reviewer, and contributor roles. GridActionBench operates independently of any proprietary platform; see `docs/project/PID.md`, "Relationship to other initiatives."

## Maintainers

See `GOVERNANCE.md`.

## Citation

See `CITATION.cff` (repository root, once populated).
