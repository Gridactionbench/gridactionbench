# Contributing to GridActionBench

Thank you for considering a contribution. See `GOVERNANCE.md` for roles and decision-making, and `docs/project/PID.md` / `docs/benchmark/BENCHMARK_CARD.md` for what this project is trying to accomplish.

## Current project status

GridActionBench is a runnable, simulation-based benchmark harness — Phase 1-3 implementation in progress, per `docs/project/PROJECT_PLAN.md` and the root `README.md`'s Status section. The core pipeline (schemas, simulator, evaluators, reference and seeded-failure agents, scenario generator, episodes, CLI) exists and is tested; see `README.md` for current counts. The highest-value contributions right now are:

- Review of the specification documents (`docs/`) — especially from energy-domain and benchmark-methodology perspectives (see `docs/research/EXPERT_REVIEW_CHECKLIST.md` for the kind of critical feedback most useful).
- Identification of gaps, errors, or unjustified assumptions in the specification — the maintainer tracks these internally; open an issue describing what you found rather than expecting a public assumptions register to check against (see `docs/benchmark/PUBLIC_PRIVATE_POLICY.md` for why some internal review material is not published).
- The code-level contributions listed below, which now have working implementations to build on rather than a blank slate.

## What you can contribute

- **Scenarios** — new or improved scenario definitions, following the schema in `docs/architecture/DATA_MODEL.md` and the review ladder in `docs/suites/gb-bess/SCENARIO_CATALOGUE.md` (DRAFT → ENGINEERING_REVIEWED → BENCHMARK_REVIEWED → VERIFIED).
- **Evaluators** — new or improved evaluator specifications/implementations, following the format in `docs/suites/gb-bess/EVALUATION_SPEC.md`.
- **Simulator adapters** — validate or extend `PSSESimulatorAdapter`, following [ADR-018](docs/architecture/adr/ADR-018-psse-power-flow-adapter.md) and the [runtime validation gates](docs/testing/RUNTIME_VALIDATION.md).
- **Agent adapters** — new reference or provider-specific agent implementations, per `docs/architecture/adr/ADR-004-agent-abstraction.md`. No provider is privileged in the core benchmark.
- **Datasets** — proposed real-world data sources, always with a complete provenance record (`docs/architecture/DATA_MODEL.md`, "Data provenance record") and confirmed licensing before any data is committed (`docs/architecture/adr/ADR-012-data-provenance.md`).
- **Documentation and research** — corrections, expansions, or challenges to any specification or research document.

## Rules for changes affecting official benchmark behaviour

See `GOVERNANCE.md`, "Changes affecting official benchmark behaviour" — a required sequence of proposal, rationale, impact assessment, tests, review, documentation, and a versioning decision. This applies to scenarios, evaluators, schemas, and scoring logic; it does not apply to typo fixes, non-normative documentation clarifications, or purely additive documentation (e.g., a new research note) that does not change any scored behaviour.

## What we will not accept

- Scenario or evaluator changes without a stated rationale and impact assessment.
- Real datasets without a complete, confirmed-licence provenance record.
- Code or scenario content copied from another project without independently verified licence compatibility (see `docs/research/PRIOR_ART.md` §8 for why this is treated carefully in this project specifically).
- Any change that would give a component the ability to address a real, physical energy asset or operational system — see `docs/architecture/SECURITY.md` and `SECURITY.md` (this file's root-level counterpart).

## Code of Conduct

All contributors are expected to follow `CODE_OF_CONDUCT.md`.

## License

By contributing, you agree that your contributions will be licensed under the project's Apache License 2.0 (`LICENSE`), and, for data contributions, under the terms documented in `DATA_LICENSES.md`.
