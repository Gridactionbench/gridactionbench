# ADR-020: Evaluation failure handling and agent execution hardening

Status: Implemented; real PSS/E and Docker validation pending.

## Problem

Non-finite actions and non-converged solves could pass hard-constraint evaluation.
An unknown generator target could terminate a run. Docker output was unbounded,
timeout cleanup was implicit, and network policy and incident attribution depended
on shared infrastructure that was not checked against each run's configuration.

## Decision

- Reject non-finite action, observation, and network numeric values. Validate network
  references and uniqueness, and reject unknown action targets before simulation.
- Require both the solver API call and its convergence status to report success.
  Do not read solved values after non-convergence. Reject incomplete/non-finite results.
- Record agent, invalid-action, and simulation errors separately using
  `evaluation_status`. Unscoreable runs cannot advance episode state or contribute
  economic scores; solver errors are not counted as proven agent violations.
- Bound Docker stdout/stderr, validate resource limits, copy and freeze environment
  configuration, run agents as UID/GID 65532, and remove named resources explicitly
  on every exit path. Cleanup failures invalidate the invocation.
- For networked runs, verify the blueprint network and canonical proxy policy,
  then create a fresh internal network and proxy per invocation. Allow only exact
  declared hostnames on port 443 and deny private destination addresses. Read only
  that invocation's proxy log. Monitoring failures invalidate the invocation.
- Keep private seeds and complete Decision Records in access-controlled evaluation
  storage. The existing private manifest remains a private reproducibility artifact.

## Compatibility and versioning

Framework version becomes 0.2.0; simulator version becomes 1.1.0. Suite/scenario
versions and evaluator IDs/formulas are unchanged. `evaluation_status` is additive
and defaults to `completed` when reading older records; older records cannot be
retroactively assumed to satisfy the new checks.

Existing well-formed, converged test scenarios retain their expected outcomes.
Previously accepted NaN values and failed solves are intentionally no longer
scoreable. Results from the older harness should be rerun before comparison.
Network-enabled callers must reprovision their proxy blueprint using the new policy.
Agent images must support execution as UID/GID 65532 and a read-only root filesystem.

## Validation and limits

Regression tests cover invalid actions, failed/incomplete solver output, process output
limits, timeouts, immutable configuration, cleanup, and proxy-policy verification.
Opt-in Docker and licensed-PSS/E checks are documented in
[runtime validation](../../testing/RUNTIME_VALIDATION.md).

No licensed PSS/E installation or Docker daemon was available during implementation.
These changes do not establish OS isolation or numerical solver correctness. Proxy
configuration verification assumes a trusted Docker administrator and blueprint image;
it cannot protect against compromise of that administrator, daemon, or host kernel.
Allowed provider traffic may contain scenario content. Dedicated evaluation hosts,
restricted daemon access, scoped provider credentials, and private artifact storage
remain required for official evaluation infrastructure.
