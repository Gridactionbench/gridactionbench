# Data Model

**Status:** Revised — Phase 0.5 methodology correction pass. Adds a scenario-level `information_requirements` block (replacing implicit global thresholds), expands `EvaluationResult.result` beyond pass/warning/failure, and adds `constraint_class`/`severity`/`ucv_eligible` to evaluator metadata. Field-level schema reference; conceptual relationships are in `docs/architecture/DOMAIN_MODEL.md`.

## EnergyObservationV1

See `docs/suites/gb-bess/SPECIFICATION.md` §2 for the full field listing and types. Serialization: JSON, versioned via `schema_version`.

## AgentActionV1

See `docs/suites/gb-bess/SPECIFICATION.md` §3 for the full field listing, types, and validation rules.

## Scenario file (source-of-truth authoring format)

YAML, one file per scenario (or, for Phase 3 generated instances, one template file plus generator config). Required top-level keys, per master brief §44:

```yaml
scenario_id: string
scenario_version: string        # semver

suite: string
suite_version: string
family: PHY | NET | OPS | MKT | DATA | ADV | HUM

source_type: synthetic | historical   # historical requires verified provenance, unused in v0.1
author: string
created_date: date

parameters: {...}               # scenario-specific numeric/categorical inputs
seed: int | null                # for any stochastic element of scenario generation

oracle: {...}                   # full ground truth, per docs/suites/gb-bess/SPECIFICATION.md §2 fields
observation_generation: {...}   # rule/spec for deriving agent_observation from oracle (identity, redaction, corruption)

information_requirements:       # scenario-defined, never a global benchmark constant
  voltage:
    required_for: [SET_GENERATION]      # which actions this field must be sufficient for; omit the
                                          # field entirely (not required_for: []) if this scenario
                                          # imposes no information requirement on voltage at all
    max_age_seconds: int | null          # scenario-defined staleness bound; null/absent = no staleness
                                          # check for this scenario (evaluator returns NOT_APPLICABLE,
                                          # never a benchmark-wide default)
    conflict_tolerance: float | null     # scenario-defined max acceptable divergence between readings
    valid_sources: [string] | null       # optional allow-list of acceptable telemetry source labels
  branch_loading:
    required_for: [SET_GENERATION]
    max_age_seconds: int | null
    plausible_upper_bound_mva: float | null   # scenario/asset-derived, never a global constant
  # additional fields (market, etc.) follow the same shape as needed

permitted_actions: [...]
prohibited_actions: [...]
preferred_actions: [...]        # optional — implemented 2026-09-09 (was named here since Phase 0
                                 # but had no code or evaluator behind it until MKT-PREFERRED-ACTION-001,
                                 # docs/suites/gb-bess/EVALUATION_SPEC.md)

escalation:
  required: bool
  permitted: bool

evaluator_coverage: [eval_id, ...]   # must match the scenario's relevant_evaluators
data_provenance: {...}               # required if source_type: historical; N/A for synthetic

review_status: DRAFT | ENGINEERING_REVIEWED | BENCHMARK_REVIEWED | VERIFIED
review_history: [...]
```

This is the format `docs/suites/gb-bess/SCENARIO_CATALOGUE.md`'s 20 initial scenarios are specified in (informally, as embedded YAML blocks); the actual JSON Schema lives under `gridactionbench/schemas/`, with the 20 initial scenarios backed by real scenario files under `suites/gb_bess/v0_1/`.

## Decision Record

See `docs/benchmark/SPECIFICATION.md` §7 for the full field listing. Serialization: **JSONL**, one record per line, append-only per run — chosen specifically because it is a portable, streaming-friendly, dependency-free format that does not require proprietary tracing infrastructure to produce or consume (master brief §13), and because it matches the logging convention already validated by related work (`docs/research/PRIOR_ART.md`, executable-evaluation benchmarks' own JSONL evidence logs).

## EvaluationResult (per-evaluator output, embedded in a Decision Record's `evaluation_results`)

```yaml
eval_id: string
version: string
constraint_class: HARD | OPERATIONAL | INFORMATION   # OBJECTIVE deliberately never appears here —
                                                        # see docs/suites/gb-bess/EVALUATION_SPEC.md
severity: LOW | MEDIUM | HIGH | CRITICAL
ucv_eligible: bool        # static per evaluator (or per evaluator *component* — see
                           # HUM-ESCALATE-CRITICAL-DATA-001's split in EVALUATION_SPEC.md), NOT derived
                           # from severity at read time — set once, at evaluator-definition time, and
                           # carried through unchanged so a report can group by it without recomputation
result: PASS | WARNING | FAIL | NOT_APPLICABLE | INDETERMINATE | EVALUATOR_ERROR
evidence: {...}          # evaluator-specific supporting data (e.g. solved resulting_voltage_pu, branch-loading margin)
contributes_to_ucv: bool  # true only if result == FAIL AND ucv_eligible == true AND (for the required-
                           # escalation case) the agent did not escalate — see
                           # docs/benchmark/SPECIFICATION.md §8 for the full UCV computation
```

`contributes_to_ucv` is a **derived, redundant-on-purpose** field — always recomputable from `result` and `ucv_eligible` plus the Decision Record's escalation outcome — stored directly on the record so reporting never has to re-derive UCV membership from first principles and risk drifting from the Evaluation Engine's own computation at run time.

## Report (aggregated output, not persisted per-record — computed from a Run's Decision Records)

```yaml
run_id: string
versions: {framework, suite, scenario_set, evaluator_set, simulator, agent_configuration}
dimensions:
  - name: string          # e.g. "Physical constraint adherence"
    pass_rate: float       # computed over PASS/WARNING/FAIL results only — see below
    n: int                 # count of PASS/WARNING/FAIL results contributing to pass_rate
    not_applicable_n: int  # reported separately, never folded into n or pass_rate
    indeterminate_n: int   # benchmark-health signal, not an agent-performance signal — reported
                            # separately; a nonzero count here is a prompt to review the scenario/
                            # evaluator, not the agent (docs/research/PRIOR_ART.md §1.1 item 4)
    evaluator_error_n: int # benchmark-health signal — a nonzero count here indicates an evaluator
                            # code defect, never attributed to the agent
ucv_count: int
self_reported_high_confidence_ucv_count: int   # renamed this pass — see docs/benchmark/SPECIFICATION.md §8
total_scenarios: int
```

Matches `docs/benchmark/SCORING.md`'s required reporting format exactly — this schema exists so the reporting format is enforced structurally, not just by convention in documentation.

## Data provenance record (for any real, licence-confirmed dataset — Phase 5)

```yaml
dataset_name: string
source: string
source_url: string
retrieval_date: date
licence: string
redistribution_status: redistributable | attribution-required | not-redistributable | unconfirmed
required_attribution: string | null
transformation: string
original_units: string
benchmark_units: string
checksum: string           # e.g. sha256
benchmark_version: string
```

Matches master brief §35 exactly. No dataset with `redistribution_status: unconfirmed` is committed to this repository — see `docs/data/DATA_SOURCES.md`.
