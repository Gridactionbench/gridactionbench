# Security Policy

## Physical-system isolation

**GridActionBench GB-BESS v0.1 is simulation-only.** No component in this repository may issue commands to, or maintain credentials for, a physical energy asset or operational energy-system interface (SCADA, EMS, inverter control, DNO control, DERMS, market bidding execution). This is an architectural guarantee, enforced by design — see `docs/architecture/SECURITY.md` and `docs/architecture/adr/ADR-015-physical-system-isolation.md` for the full statement and enforcement mechanism. This is a scope boundary for the current environment, not a permanent limit on the project: future GridActionBench environments may examine controlled digital-twin, hardware-in-the-loop, laboratory or sandboxed operational settings, subject to separate safety, security, governance and validation requirements, and would require an entirely new, separately-approved architecture (`docs/architecture/adr/ADR-015-physical-system-isolation.md`, "Consequences").

If you believe you have found a code path, dependency, or schema field that could plausibly reach a real operational endpoint, **report it immediately** as described below — this is treated as the highest-severity class of issue this project can have.

## Reporting a vulnerability or isolation concern

Use [GitHub private vulnerability reporting](https://github.com/igwebupower/gridactionbench/security/advisories/new) when enabled. A monitored private reporting channel must be configured before release; an alternative security email has not yet been published. Do not place vulnerability details or credentials in public issues. Include:

- A description of the concern.
- Steps to reproduce, if applicable.
- The affected file(s) or component(s).

## Scope

This policy covers the GridActionBench codebase, its documented dependencies, and its evaluation infrastructure (public and, once built, private — `docs/benchmark/PUBLIC_PRIVATE_POLICY.md`). It does not cover any real energy asset, network, or market system — none are integrated with this project, by design.

## Execution and private evaluation material

The Docker backend is experimental and has not been validated against a real daemon
in the implementation environment. It defaults to no networking. Networked execution
uses an exact hostname/port policy and separate per-run networks and proxies, with
bounded output and explicit cleanup. These controls do not establish protection
against host/kernel compromise or disclosure through an allowed provider request.

Keep Docker administration, provider keys, PSS/E licensing material, private seeds,
selection manifests, and raw Decision/Trajectory Records in access-controlled
evaluation infrastructure. Private manifests intentionally retain the generation seed
for reproducibility; they are not publication artifacts. `.gitignore` is not an
access-control boundary. See [runtime validation and release gates](docs/testing/RUNTIME_VALIDATION.md).

## Other integrity concerns

For benchmark-integrity concerns that are not security vulnerabilities in the traditional sense (e.g., suspected evaluator gaming, contamination, or holdout leakage), see `docs/benchmark/THREAT_MODEL.md` and report through the same channel — these are taken seriously as threats to the project's research validity even when they carry no traditional "CVE" framing.
