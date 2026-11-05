# Security

**Status:** Draft — Phase 0. These are architectural guarantees, not policy aspirations.
Two deliberately distinct sections below — don't conflate them: Physical-System Isolation
is about the *simulated energy system* never reaching a real grid asset; Agent Execution
Sandbox is about the *agent process being evaluated* never leaking held-out data or
reaching the open internet.

## Physical-System Isolation

### The guarantee

**No component in GB-BESS v0.1 may issue commands to a physical energy asset or operational energy-system interface.** GB-BESS v0.1 is simulation-only.

### What is not implemented, by design

- SCADA command interfaces
- EMS (Energy Management System) write interfaces
- Inverter control interfaces
- DNO control interfaces
- Live DERMS write access
- Market bidding execution (no connection to any real Balancing Mechanism, exchange, or trading venue)
- Physical asset credentials of any kind (no API keys, certificates, or network access scoped to a real BESS, DNO, or NESO operational system are used, stored, or referenced anywhere in this codebase)

### How the architecture enforces this, not just states it

- The `SimulatorAdapter` interface (`docs/architecture/ARCHITECTURE.md`) has no method that accepts a real-world endpoint, credential, or device identifier — its entire input/output surface is `(pre_state, action) -> post_state`, operating purely on in-memory or file-backed simulated state.
- `EnergyObservationV1` and `AgentActionV1` (`docs/suites/gb-bess/SPECIFICATION.md`) contain no fields for physical-device addressing (no IP addresses, device IDs, SCADA point identifiers, or control-system endpoints) — the schemas are structurally incapable of routing an action anywhere but the simulator.
- No dependency on any commercial or open-source SCADA/EMS/DERMS client library is introduced anywhere in `gridactionbench/`.
- Any `SimulatorAdapter` implementation for a real power-system simulator (e.g. the PSS/E-backed adapter, `docs/architecture/adr/ADR-018-psse-power-flow-adapter.md`) is explicitly scoped to *simulation* engines operating on a self-contained, synthetic case — never a live control system — this document's guarantee extends to any such adapter by definition, not merely to the original `SimpleBessSimulator`.

### Threat model relationship

Physical-system isolation is an architectural property, distinct from the benchmark-integrity threats catalogued in `docs/benchmark/THREAT_MODEL.md`. This document exists because master brief §57 requires it to be stated and enforced explicitly, independent of and prior to any discussion of benchmark-gaming or contamination risk.

### Review obligation

Any pull request introducing a new `SimulatorAdapter`, a new dependency with network-call capability, or any code path that could plausibly reach a real operational endpoint must be reviewed against this document before merge, per the contribution governance in `GOVERNANCE.md`. This is a standing review obligation, not a one-time Phase 0 checklist item.

## Agent Execution Sandbox

**The guarantee:** an evaluated agent (any LLM-backed, tool-using, or third-party
submission) cannot leak held-out scenario or ground-truth data out of an evaluation run,
and cannot reach the open internet to look up an answer externally instead of reasoning
over the observation it was actually given. See
`docs/architecture/adr/ADR-019-agent-execution-sandbox.md` for the full decision record —
summarized here:

- **Who needs it:** reference/baseline agents (`always_idle`, `always_escalate`,
  `rule_based`, `mpc_lookahead`, the seeded-failure agents) are maintainer-authored,
  deterministic, and confirmed to make zero network calls — they run in-process, as
  today. Only evaluated/untrusted agents need sandboxing, and specifically whenever run
  against held-out content.
- **How:** `gridactionbench/agents/sandboxed.py::SandboxedAgentAdapter` implements the
  existing `AgentAdapter` protocol unchanged, delegating to `DockerSandboxBackend`
  (`gridactionbench/agents/docker_backend.py`) — one fresh, ephemeral, capability-dropped,
  read-only container per invocation, default `--network none`, with a narrow,
  allowlisted egress path (`scripts/sandbox/`) only when an agent genuinely needs to call
  its own model provider's API.
- **What crosses the boundary:** `EnergyObservationV1` JSON in, `AgentActionV1` JSON out
  — nothing else. The `Scenario`/`Oracle` ground truth is never constructed in a form a
  sandboxed process could reach. `SandboxConfig` refuses, at construction time, to be
  built with the private holdout seed or any `GRIDACTIONBENCH_PRIVATE_*` environment
  variable.
- **What this does not do:** detect training-data contamination
  (`docs/benchmark/CONTAMINATION_POLICY.md`'s separate problem), or inspect the content
  of an otherwise-legitimate request to an *allowed* model-provider host — both stated
  explicitly as open limitations in ADR-019, not silently assumed away.

### Review obligation

Any pull request changing `gridactionbench/agents/sandboxed.py`,
`gridactionbench/agents/docker_backend.py`, or `scripts/sandbox/` must be reviewed against
ADR-019 before merge — the same standing obligation as the physical-system-isolation
review above, for this separate guarantee.
