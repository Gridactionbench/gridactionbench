"""DockerSandboxBackend — the real `SandboxBackend` implementation.

The only module that shells out to the `docker` CLI, and does so lazily (inside each
function call, not at import time) — mirrors
`gridactionbench/simulators/psspy_client.py`'s isolation pattern for the same reason: the
rest of the codebase must stay importable on a machine with no Docker installed, and
tests substitute a fake backend (`tests/fakes/fake_sandbox_backend.py`) instead of this
one.

**Honesty note (see docs/architecture/adr/ADR-019-agent-execution-sandbox.md):** this
backend is written against `docker run`'s documented CLI flags as carefully as possible,
but has not been executed against a real Docker daemon in this project's own development
environment (no Docker installed here). It has been exercised only through the fake
backend. Anyone deploying this for a real Verified-tier run must validate it against
their own Docker host before trusting it.

Egress allowlisting beyond "no network at all" requires a pre-provisioned Docker network
attached to an allowlisting egress proxy — this backend does not provision that network
itself (that is real infrastructure, not a `docker run` flag); see
`scripts/sandbox/README.md` for how to provision one. This backend only *attaches* to an
already-provisioned network by name, and refuses to run at all rather than guess a
network policy if the caller's `SandboxConfig` and this backend's own configuration
disagree about whether one is needed.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone

from gridactionbench.agents.sandboxed import SandboxConfig, SandboxRunResult

# Docker's own convention for "no network interface at all" — the default, strongest
# policy, used whenever a SandboxConfig declares no allowed_hosts.
NO_NETWORK = "none"


class SandboxBackendError(RuntimeError):
    """Raised when the Docker-based sandbox mechanism itself fails to run (not when the
    *agent* inside it errors or returns malformed output — that is a normal, recorded
    outcome handled by SandboxedAgentAdapter.act(), not a backend failure)."""


def _require_docker() -> str:
    docker_path = shutil.which("docker")
    if docker_path is None:
        raise SandboxBackendError(
            "docker is not installed or not on PATH — DockerSandboxBackend requires a "
            "working Docker host. Use tests/fakes/fake_sandbox_backend.py for tests."
        )
    return docker_path


class DockerSandboxBackend:
    """Runs one agent invocation in a fresh, ephemeral Docker container per call —
    created, used once, and torn down (`--rm`) every time. No container is ever reused
    across invocations, so no agent-writable state can persist between scenarios."""

    def __init__(self, image: str, egress_network: str | None = None, egress_proxy_container: str | None = None):
        """`image` is the agent's own Docker image (built by whoever submits the agent —
        out of scope for this backend, which only runs it, never builds it).
        `egress_network` is the name of a pre-provisioned Docker network attached to an
        allowlisting egress proxy (`scripts/sandbox/provision_network.sh`); required
        whenever a `SandboxConfig` passed to `run()` declares a non-empty `allowed_hosts`.
        `egress_proxy_container` is that same proxy's own container name, used to query
        its access log for denied connections after each run (see `_blocked_egress_since`
        below) — required under the same condition as `egress_network`. Leave both `None`
        for the default, fully network-isolated case.
        """
        self.image = image
        self.egress_network = egress_network
        self.egress_proxy_container = egress_proxy_container

    def run(self, observation_json: str, config: SandboxConfig) -> SandboxRunResult:
        # Checked before requiring Docker itself: a config/backend mismatch is a logic
        # error independent of whether a Docker host is even available, and should fail
        # with that specific message rather than being masked by "docker not installed."
        if config.allowed_hosts and not self.egress_network:
            raise SandboxBackendError(
                f"SandboxConfig declares allowed_hosts={config.allowed_hosts!r} but this "
                "backend has no egress_network configured — refusing to run with an "
                "ambiguous network policy rather than silently falling back to either "
                "fully-open or fully-closed network access."
            )

        docker_path = _require_docker()

        network = self.egress_network if config.allowed_hosts else NO_NETWORK

        cmd = [
            docker_path, "run",
            "--rm", "-i",
            "--network", network,
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "--memory", f"{config.memory_limit_mb}m",
            "--cpus", str(config.cpu_limit),
            "--pids-limit", str(config.pids_limit),
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
        ]
        if config.allowed_hosts and self.egress_proxy_container:
            # Belt-and-suspenders, not the sole protection: a well-behaved agent that
            # respects HTTPS_PROXY reaches the allowlist through it directly. A
            # misbehaving agent that ignores these and tries a direct connection still
            # can't reach the open internet at all, because `egress_network` is itself
            # provisioned with no outbound route except through this same proxy
            # container (scripts/sandbox/provision_network.sh, `--internal`) — the env
            # var is a convenience for cooperative agents, not the enforcement boundary.
            proxy_url = f"http://{self.egress_proxy_container}:3128"
            cmd += ["-e", f"HTTPS_PROXY={proxy_url}", "-e", f"HTTP_PROXY={proxy_url}"]
        for key, value in config.env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd.append(self.image)

        # The egress proxy, not the agent container, is what actually observes a denied
        # connection (it's a shared, longer-lived piece of infrastructure, not spun up
        # fresh per invocation) — so blocked attempts are attributed by querying its log
        # for the time window this one invocation ran in, not by parsing the agent
        # container's own stdout/stderr, which never sees the proxy's decision at all.
        started_at = datetime.now(timezone.utc)
        try:
            completed = subprocess.run(
                cmd,
                input=observation_json,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxBackendError(
                f"sandboxed agent {self.image!r} did not return within "
                f"{config.timeout_seconds}s"
            ) from exc
        finished_at = datetime.now(timezone.utc)

        if completed.returncode != 0:
            raise SandboxBackendError(
                f"sandboxed agent {self.image!r} exited {completed.returncode}: "
                f"{completed.stderr.strip()[:2000]}"
            )

        blocked = ()
        if self.egress_proxy_container is not None:
            blocked = self._blocked_egress_since(started_at, finished_at)

        return SandboxRunResult(action_json=completed.stdout.strip(), blocked_egress_attempts=blocked)

    def _blocked_egress_since(self, started_at: datetime, finished_at: datetime) -> tuple[str, ...]:
        """Queries the egress proxy container's own log (Squid's default access-log
        format — see `scripts/sandbox/egress_proxy/squid.conf.template`) for `TCP_DENIED`
        entries logged between `started_at` and `finished_at`, attributing them to this
        invocation by time window since the proxy is shared across invocations rather
        than created fresh per call. `docker logs --since/--until` takes RFC3339
        timestamps directly. Best-effort: a proxy/log-format mismatch yields no blocked
        attempts rather than raising, so a logging hiccup never masks the agent's actual
        returned action."""
        docker_path = _require_docker()
        try:
            result = subprocess.run(
                [
                    docker_path, "logs",
                    "--since", started_at.isoformat(),
                    "--until", finished_at.isoformat(),
                    self.egress_proxy_container,
                ],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return ()
        return _parse_squid_denied_hosts(result.stdout)


def _parse_squid_denied_hosts(proxy_log: str) -> tuple[str, ...]:
    """Squid's default access.log line shape is roughly
    `<time> <elapsed> <client> <code>/<status> <bytes> <method> <url> ...` — a denied
    CONNECT shows `TCP_DENIED` as the code and the target `host:port` as the URL for a
    CONNECT method. Parsed defensively field-by-field; a line that doesn't match this
    shape is skipped, not treated as an error."""
    hosts: list[str] = []
    for line in proxy_log.splitlines():
        fields = line.split()
        if len(fields) < 7:
            continue
        code_status, method, url = fields[3], fields[5], fields[6]
        if "TCP_DENIED" in code_status and method == "CONNECT":
            hosts.append(url.rsplit(":", 1)[0])
    return tuple(hosts)
