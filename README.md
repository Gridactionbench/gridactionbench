# GridActionBench

GridActionBench is an open-source research benchmark for evaluating AI agents making decisions in simulated power systems. The current direction uses Siemens PSS®E through its `psspy` Python API for offline power-flow studies on small synthetic networks.

Agents receive a structured observation and return a generator setpoint, an idle action, or an escalation. The harness evaluates constraint adherence, information handling, escalation, adversarial resilience, and economic decision quality, with results recorded separately by dimension.

## Status and scope

The repository contains a Python library, CLI, synthetic scenarios, reference agents, evaluators, scenario generation, multi-step episodes, and result reporting. The power-flow model replaces the earlier battery energy storage model. Existing `gb_bess` package names, `GB-BESS-*` scenario identifiers, and the `suites/gb_bess/v0_1/` directory remain for continuity; the bundled scenario files declare suite version `0.2.0`.

The PSS®E integration is under development:

- The adapter has been tested against a fake `psspy` implementation, not a licensed PSS®E installation. API compatibility and numerical correctness on real PSS®E remain unverified.
- Bus voltages use the PSS®E solve path. Branch loading uses declared linear sensitivities and generator output, rather than solved PSS®E branch flows.
- The synthetic case is a simplified network model, not a validated representation of an operational grid. Scenarios are marked `DRAFT`.
- Docker-based agent isolation is implemented but has not been validated against a real Docker daemon in the project's development environment.

This is an offline simulation environment. It contains no integration for controlling physical energy assets or submitting operational market bids. See the [security policy](SECURITY.md) and the [power-flow adapter decision](docs/architecture/adr/ADR-018-psse-power-flow-adapter.md).

## Installation

The harness requires Python 3.11 or later. From a source checkout, create and activate a virtual environment, then install:

```bash
python -m pip install -e ".[dev]"
```

Running simulations additionally requires a separately licensed PSS®E installation with `psspy` importable by the Python interpreter running the harness. Confirm interpreter compatibility with your installed PSS®E release; the project's Python requirement alone does not establish that compatibility. PSS®E and `psspy` are not distributed with this repository or installed by pip as project dependencies.

For reproducible development, use `uv sync --locked --extra dev` with [uv.lock](uv.lock). The [requirements file](requirements-lock.txt) is a generated export for pip users. See [runtime validation](docs/testing/RUNTIME_VALIDATION.md) for dependency updates, CI checks, and the remaining release gates.

## Usage

Inspect the CLI and bundled scenarios without PSS®E:

```bash
gridactionbench --help
gridactionbench list-scenarios suites/gb_bess/v0_1/scenarios
gridactionbench coverage
```

With a compatible, licensed PSS®E environment configured:

```bash
gridactionbench run suites/gb_bess/v0_1/scenarios --agent rule-based
gridactionbench run-generated --agent rule-based --n-per-template 15 --seed 42
```

Use `--output runs/decisions.jsonl` with `run` to save Decision Records. These records include observations, ground truth, evaluator evidence, and provenance; review them before publishing results from private scenarios.

The CLI currently selects built-in agents. External agents can use the Python adapter interfaces; see the [agent sandbox decision](docs/architecture/adr/ADR-019-agent-execution-sandbox.md) and [sandbox setup](scripts/sandbox/README.md) for the experimental Docker backend.

## Development and testing

```bash
python -m pytest -q
```

The test suite injects a fake `psspy` module automatically, so it runs without PSS®E. Passing tests verify harness behavior against that double; they do not establish real solver accuracy or Docker isolation. See the [test strategy](docs/testing/TEST_STRATEGY.md).

## Evaluation model

```text
Scenario -> Observation -> Agent -> Structured action
         -> Simulation and evaluation -> Decision record -> Report
```

The evaluator uses scenario ground truth separately from the agent-visible observation. Scenarios can introduce missing, stale, conflicting, or adversarial information. Single-step runs produce Decision Records; multi-step episodes also support Trajectory Records. Results are reported by dimension rather than combined into a single score.

## Repository layout

```text
gridactionbench/  schemas, simulation adapters, evaluation, runners, reporting, CLI
baselines/        reference agents and deliberately failing agents
suites/gb_bess/   synthetic power-flow scenarios under legacy suite names
tests/            unit, integration, golden, and reproducibility tests
scripts/          scenario utilities and experimental sandbox infrastructure
docs/             methodology, specifications, architecture, and project documentation
```

## Documentation and contributions

- [Benchmark specification](docs/benchmark/SPECIFICATION.md) and [scoring](docs/benchmark/SCORING.md)
- [Reliability boundary model](docs/benchmark/RELIABILITY_BOUNDARY_MODEL.md) and [task model](docs/benchmark/TASK_MODEL.md)
- [Suite specification](docs/suites/gb-bess/SPECIFICATION.md) and [evaluation specification](docs/suites/gb-bess/EVALUATION_SPEC.md)
- [PSS®E migration decision and limitations](docs/architecture/adr/ADR-018-psse-power-flow-adapter.md)
- [Public/private evaluation policy](docs/benchmark/PUBLIC_PRIVATE_POLICY.md)
- [Contributing](CONTRIBUTING.md), [governance](GOVERNANCE.md), and [code of conduct](CODE_OF_CONDUCT.md)

Some planning documents and historical results still describe the earlier battery model. They should not be treated as validation of the current power-flow implementation.

## License and citation

Project code and contributor-authored synthetic scenarios are licensed under [Apache License 2.0](LICENSE); see [data licensing](DATA_LICENSES.md) for details. PSS®E is proprietary software subject to its own license.

Citation metadata is available in [CITATION.cff](CITATION.cff). Include the commit and component versions used when reporting results.
