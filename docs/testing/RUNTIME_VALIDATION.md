# Runtime validation and release gates

The default suite uses a fake `psspy` module and mocked Docker orchestration.
It does not establish real solver accuracy or container isolation.

## Reproducible development checks

Install uv 0.13.7, then run:

```bash
uv sync --locked --extra dev --group quality
uv run --no-sync python -m pytest -q
uv run --no-sync gridactionbench --help
uv run --no-sync pip-audit --local --skip-editable
uv run --no-sync python -m build --no-isolation
```

`uv.lock` includes dependency hashes and platform markers. `requirements-lock.txt`
is its generated runtime/development export for pip users. After an intentional
dependency update, run `uv lock --upgrade` followed by:

```bash
uv export --locked --extra dev --no-emit-project --no-hashes --no-header --output-file requirements-lock.txt
```

The CI workflow checks Windows/Linux on Python 3.11 through 3.14, builds the package,
audits dependencies, checks the requirements export, and scans reachable Git history
with Gitleaks. CI has not run until the changes are pushed. The Gitleaks action may
require a license if the repository is transferred to a GitHub organization.

## Docker (opt-in, dedicated Linux Docker host)

Run only repository-owned test agents on a disposable host without evaluation secrets.
From the repository root, with the development environment active:

```bash
docker build -t gab-test-agent scripts/sandbox/test_agent
export GRIDACTIONBENCH_DOCKER_TEST_IMAGE=gab-test-agent
python -m pytest -m docker -q
```

This checks normal execution, timeout/output-limit cleanup, and concurrent offline
invocations. The manual CI workflow runs those checks on a hosted Linux runner.
For network-policy checks, provision an `example.com` blueprint as described in
[sandbox setup](../../scripts/sandbox/README.md), then set:

```bash
export GRIDACTIONBENCH_TEST_EGRESS_NETWORK=gab-test-blueprint
export GRIDACTIONBENCH_TEST_EGRESS_PROXY=gab-test-proxy
python -m pytest -m docker -q
```

The network test checks direct egress denial, port-policy denial, isolated concurrent
logs, and cleanup. Before accepting hostile submissions, also exercise attempts to
reach host services, peer containers, metadata services, DNS exfiltration, IPv6 routes,
allowed-provider HTTPS, proxy crashes, and daemon interruption on the deployment's
actual Docker version. Record Docker/kernel/image versions and the results.
These checks remain release gates; skipped tests do not count as verification.

## PSS/E (licensed installation)

Use a supported PSS/E/Python pair and the release's own API documentation to verify
case construction, machine limits, plant voltage settings, slack generation, loads,
branch parameters, and `fnsl`/`solved` status semantics. The current case builder is
minimal and has not been verified against that documentation or a licensed runtime.

Prepare an independently checked synthetic reference JSON outside public/private
production holdouts. It must contain:

- `psse_version`, `python_version`, and `reference_method` strings describing the
  installed runtime and how the expected values were obtained.
- `network_model` in the current schema and `action` in the action schema.
- `expected.bus_voltages_pu` and `expected.generator_outputs_mw`, keyed by bus ID.

With the licensed module importable and the project installed in that interpreter:

```bash
export GRIDACTIONBENCH_PSSE_REFERENCE=/path/to/independent-reference.json
python -m pytest -m psse -q --junitxml=reports/local/psse-validation.xml
```

The `psse` marker disables the automatic fake. Expected numbers must come from an
independent calculation or reviewed PSS/E case, not from this adapter or its fake.
Repeat with valid, overloaded, near-limit, and non-convergent cases. The current test
is a reference-comparison entry point, not a complete power-flow validation suite.
Branch loading remains a declared sensitivity approximation and must not be described
as solved PSS/E branch flow. Publish numerical validation only after engineering review.

## Repository access (maintainer settings)

Before release, verify these settings in the repository's current GitHub location:

- Enable private vulnerability reporting or publish a monitored security email.
- Protect the default branch: require CI and review, restrict force pushes/deletion,
  and define narrowly scoped bypass permissions. CODEOWNERS alone does not enforce this.
- Restrict release/tag creation and use protected release environments for credentials.
- Do not expose secrets or private holdouts to fork pull requests or untrusted runners.
- Keep Docker administration and PSS/E license material outside submitted agents.
- Keep seeds, selection manifests, raw Decision/Trajectory Records, and provider keys
  in private evaluation storage. Generate separate aggregate public reports.

These remote settings cannot be established by adding files to this repository.
