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

The experimental sandbox passes observation JSON to an isolated agent and validates
its returned action JSON. It uses no host-path mounts, defaults to no networking,
bounds captured output, applies resource limits, and removes per-run resources
explicitly. Configuration excludes private evaluation environment variables and
cannot be changed after validation.

Networked runs verify a canonical proxy policy and create separate networks/proxies
for each invocation. Proxy errors invalidate the run. Allowed provider requests can
still contain scenario content; TLS payloads are not inspected. Isolation depends
on the Docker daemon, kernel, deployment network, and trusted blueprint image.

These mechanisms have unit coverage but have not been verified on a real Docker
host here. They are not a guarantee against holdout extraction. Before running
untrusted submissions, complete the checks in
[Runtime validation](../testing/RUNTIME_VALIDATION.md). Keep holdouts, credentials,
and raw results in separate access-controlled evaluation infrastructure.

Changes to the sandbox must be reviewed against
[ADR-020](adr/ADR-020-execution-hardening.md), which updates the shared-network and
logging behavior originally described in ADR-019.
