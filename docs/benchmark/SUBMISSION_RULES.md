# Submission Rules

**Status:** Draft — Phase 0. No submission service exists yet; this document specifies the intended protocol for when Reference/Extended Track results are published, informed by MLPerf's Closed/Open division precedent (see `docs/research/PRIOR_ART.md` §5).

## Reference Track

To be reported as a Reference Track result, a run must hold fixed, exactly as published for the cited benchmark/suite/scenario/evaluator/simulator version:

- Benchmark, suite, scenario-set, evaluator-set, and simulator versions (all six, per `VERSIONING.md`)
- The scenario protocol (Mode A single-step or Mode B episode, as defined per scenario)
- Information available to the agent (exactly the fields in `EnergyObservationV1` for that scenario — no supplementary retrieval, no additional tool access beyond what the scenario schema provides)
- The action schema (`AgentActionV1`, unmodified)
- Any allowed tool/validation budget, where a scenario defines one

**Agent architecture may differ freely** within the Reference Track — an LLM agent, a rule-based controller, and an RL policy are all eligible Reference Track participants, evaluated on identical footing. This is the direct analogue of MLPerf's Closed division: comparing decision-making approaches "apples-to-apples" against a fixed task.

**For any GridActionBench Verified run, "no supplementary retrieval, no additional tool access" above is enforced technically, not just expected by disclosure.** The Agent Execution Sandbox (`docs/architecture/adr/ADR-019-agent-execution-sandbox.md`) runs the agent with default-deny network egress; a Reference Track agent gets no network path at all beyond, at most, its own declared model-provider API call. This closes the gap `docs/benchmark/THREAT_MODEL.md` previously left open (an honest submitter following this rule versus a submission that simply doesn't disclose honestly) for the one tier of result where it matters most. Local Result and Reproducible Submission runs are not required to use the sandbox and remain governed by disclosure alone, as before.

## Extended Track

Permits experimentation with additional tools, retrieval, extra context beyond the standard observation, alternate simulators, novel multi-agent workflows, or additional models/ensembling. Extended Track results are always reported with an explicit list of what was added beyond the Reference Track configuration.

**Reference and Extended Track results are never presented as directly equivalent** — no report, chart, or table may place a Reference Track score and an Extended Track score in the same comparison column without an explicit, visible track label on each (see `docs/benchmark/SCORING.md`, "Reference vs. Extended track scores are never merged").

## Required disclosure for any published result (Reproducible Submission tier)

- Model provider, model id, model version (where available)
- Prompt / policy configuration and its hash
- Temperature and other sampling parameters
- Tool definitions and retry strategy, if any
- Number of trials (stochastic agents must report the full trial distribution, not a single run — `METHODOLOGY.md` §7)
- Random seed(s)
- git commit of the GridActionBench code used
- Execution timestamp and environment metadata

A submission missing any of the above is a **Local Result** only and must not be described as a Reproducible Submission (`docs/benchmark/PUBLIC_PRIVATE_POLICY.md`, result status categories).

## GridActionBench Verified

Requires evaluation against official private holdout infrastructure (not yet built as of Phase 0 — see `PUBLIC_PRIVATE_POLICY.md`, "Private evaluation infrastructure"). No result can carry Verified status until that infrastructure exists and the run has been independently executed against it. This document will be updated with the concrete submission mechanism once that infrastructure is built; no submission API or leaderboard is planned for the v0.1 release itself (master brief §40, §84).

## Prohibited practices

- Tuning a submission against official hidden/holdout tests (master brief §76, §86).
- Cherry-picking the best of several stochastic trials and reporting it as representative (master brief §54, §78).
- Presenting a Local Result as if it were Verified.
- Omitting UCV counts or any required dimension from `docs/benchmark/SCORING.md`'s reporting format.
- Mixing Reference and Extended Track results without labeling.

## Independence

Submission and evaluation infrastructure described here is independent of any proprietary platform; no submission path requires access to or tooling from a specific commercial product (`docs/project/PID.md`).
