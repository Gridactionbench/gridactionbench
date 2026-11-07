# ADR-019: Agent Execution Sandbox

**Status:** Proposed

## Context
Two distinct threats are currently unhandled, confirmed by a direct audit of the codebase
and every relevant policy document before this ADR was written:

1. **Leakage** — held-out scenario content, or the full `Scenario`/`Oracle` ground truth,
   escaping an evaluation run via the evaluated agent's own network access, logs, or
   filesystem writes.
2. **Cheating** — an agent using network/tool access to look up the answer externally
   (web search, a cached copy of this benchmark's own public repo, a leaderboard) instead
   of reasoning over the `EnergyObservationV1` it was actually given.

Today, `gridactionbench/agents/base.py`'s `AgentAdapter` is a bare `typing.Protocol`
(`act(observation) -> action`) called in-process, same Python interpreter, no isolation —
`gridactionbench/runners/single_step.py:42` is the only call site in the repo. No agent
implementation anywhere makes a real network call; `LLMStructuredAgent`, the planned
LLM-backed reference agent, is explicitly deferred and never built
(`docs/project/BACKLOG.md`). `docs/benchmark/THREAT_MODEL.md`'s "Malicious tool output"
row currently states a tool-using agent's own external calls are **"out of
GridActionBench's direct control"** — an explicit, current admission this isn't handled.
`docs/architecture/SECURITY.md` and ADR-015 address a *different* axis entirely
(preventing the simulator from reaching a real physical grid/SCADA endpoint) — not agent
network egress or ground-truth exposure; don't conflate the two, "isolation" is already an
overloaded word in this repo.

The "GridActionBench Verified" result tier — the one that would run an agent against true
held-out scenarios — requires a private evaluation repository
(`gridactionbench-evaluation-private`, ADR-011) that exists but is empty: no seed, no
holdouts, no official-run protocol yet. This sandbox is the missing piece that makes
building that tier safe to do later; it is new ground, not a patch to something broken.

## Decision
Add `gridactionbench/agents/sandboxed.py::SandboxedAgentAdapter`, a new `AgentAdapter`
implementation (not a change to the protocol or to the runner — the existing
`act(observation) -> action` seam is exactly where a real process boundary can be
inserted). It delegates to a `SandboxBackend`:

- **`DockerSandboxBackend`** (`gridactionbench/agents/docker_backend.py`) — the real
  implementation. One fresh, ephemeral container per agent invocation, `--rm`'d after;
  `--read-only` root filesystem; `--cap-drop ALL`; resource limits (memory/CPU/pids).
  Default network policy is `--network none` — no interface at all. An agent that
  genuinely needs to call its own model provider's API attaches instead to a
  pre-provisioned, `--internal` Docker network fronted by an allowlisting Squid proxy
  (`scripts/sandbox/`) — `--internal` means the network itself has no outbound route
  except through that proxy container, regardless of whether the agent's own code
  respects the `HTTPS_PROXY` env var the backend sets for it; that is the actual
  enforcement boundary, the env var is a convenience for cooperative agents.
- **`FakeSandboxBackend`** (`tests/fakes/fake_sandbox_backend.py`) — the test double.
  Wraps a plain Python callable after a real JSON serialize/deserialize round trip, so
  tests can verify `SandboxedAgentAdapter`'s own orchestration logic. It provides **no**
  real OS-level isolation of its own and makes no claim to.

Only `EnergyObservationV1` JSON ever crosses into the sandbox and only `AgentActionV1`
JSON ever crosses back out — `SandboxConfig` has deliberately no "mount a host path"
field at all, so there is nothing for a misconfiguration to expose. `SandboxConfig`
itself refuses, at construction time, to be built with any
`GRIDACTIONBENCH_PRIVATE_*`-prefixed environment variable — enforced once, in the config
layer, independent of which backend consumes it, rather than trusted to each backend's
own discipline.

A blocked egress attempt is surfaced as a `SandboxIncident` and **raised by default** — a
caller must explicitly opt in to a logging callback (`on_incident`) to keep a run going
despite one; the default is "never silently dropped," matching
`docs/benchmark/THREAT_MODEL.md`'s existing discipline for other threat rows.

**Trust tiers:** reference/baseline agents (`always_idle`, `always_escalate`,
`rule_based`, `mpc_lookahead`, the seeded-failure agents) are maintainer-authored,
deterministic, and confirmed to make zero network calls — they keep running in-process
exactly as today; sandboxing them would be pure overhead for no safety gain. Only
evaluated/untrusted agents (any LLM-backed or tool-using agent, any third-party
submission) need the sandbox, and specifically whenever run against held-out content.

## Alternatives considered
- **Enforce isolation purely through `SUBMISSION_RULES.md`'s existing disclosure rule**
  ("no supplementary retrieval") — rejected as the sole mechanism: a disclosure rule an
  honest submitter follows does nothing against a submission that simply doesn't disclose
  honestly, which is exactly the threat this ADR exists to address technically, not just
  procedurally.
- **A lighter-weight restricted-subprocess sandbox (env/cwd scrubbing only, no container)**
  instead of Docker — rejected: on a non-Linux host (or without root for network
  namespaces), there is no reliable, cross-platform way to actually block a child
  process's sockets at the OS level without a container or VM boundary; a subprocess-only
  approach could prove the adapter's *orchestration* logic correct (which is what
  `FakeSandboxBackend` already does) but could not back it with a real network-isolation
  guarantee.
- **A managed cloud microVM/sandbox product instead of Docker** — not chosen: decided
  with the project owner in favor of Docker hosted on a cloud VM/managed container
  service, for operational simplicity and no vendor lock-in; revisit if stronger
  isolation (e.g. a gVisor runtime or Firecracker-based service) is later judged necessary
  for a specific threat this doesn't cover.

## Consequences
- Positive: closes `docs/benchmark/THREAT_MODEL.md`'s "Malicious tool output" and
  "Hidden-set extraction" rows with an actual enforced mechanism instead of an admitted
  gap; makes `SUBMISSION_RULES.md`'s Reference Track "no supplementary retrieval" rule a
  technical default for any Verified-tier run, not an honor-system expectation.
- Positive: required no change to `AgentAdapter`, the runner, or any evaluator — the
  existing Oracle/Observation separation (ADR-005) and the `act(observation) -> action`
  seam already pointed at exactly this boundary.
- Negative, stated plainly: this does not, and cannot, detect **training-data
  contamination** (a model that memorized a public scenario during pretraining) — that is
  `docs/benchmark/CONTAMINATION_POLICY.md`'s separate problem; an execution sandbox cannot
  retroactively un-contaminate a model's weights.
- Negative, stated plainly: this does not stop an agent from encoding held-out scenario
  content *inside an otherwise-legitimate request* to its own allowed model provider, who
  may itself retain logs — the proxy restricts *which hosts* are reachable, it does not
  (and architecturally should not, since it never terminates TLS) inspect *what* is sent
  to an allowed one. Not solved in this version; worth a future ADR if it proves to
  matter in practice.
- Negative, stated plainly: `DockerSandboxBackend` and `scripts/sandbox/` are written
  against Docker's and Squid's documented behaviour but have not been executed against a
  real Docker host in this project's own development environment (none is installed
  here). Unverified until run against a real Docker host — see both modules' own honesty
  notes.
- Negative: does not stop a determined agent from encoding information in its *action*
  choice pattern across many runs as a side channel — out of scope for this version.
