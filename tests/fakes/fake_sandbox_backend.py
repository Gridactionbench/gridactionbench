"""Fake `SandboxBackend` — a test double standing in for a real Docker-based sandbox.

Exists so this benchmark's test suite can exercise `SandboxedAgentAdapter`'s own
orchestration logic (config construction, result handling, incident reporting) without a
Docker daemon (see docs/architecture/adr/ADR-019-agent-execution-sandbox.md).

**This fake provides NO real OS-level network or filesystem isolation of its own** — it
does not prove a real sandbox is secure; it proves `SandboxedAgentAdapter` builds the
right request and handles the backend's response correctly. Real isolation guarantees
come from `DockerSandboxBackend`'s `--network`/`--read-only`/capability-dropping flags,
which require a real Docker host to verify (unverified in this project's own
environment — see that backend's own module docstring).
"""

from __future__ import annotations

from typing import Callable

from gridactionbench.agents.sandboxed import SandboxConfig, SandboxRunResult


class FakeSandboxBackend:
    """Wraps a plain Python callable (`agent_fn(observation_json) -> action_json`) as if
    it were running inside a sandbox. Records every config it was called with, and can be
    told to simulate a blocked-egress attempt via `simulate_blocked_hosts`."""

    def __init__(self, agent_fn: Callable[[str], str]):
        self.agent_fn = agent_fn
        self.calls: list[SandboxConfig] = []
        self.simulate_blocked_hosts: tuple[str, ...] = ()

    def run(self, observation_json: str, config: SandboxConfig) -> SandboxRunResult:
        self.calls.append(config)
        action_json = self.agent_fn(observation_json)
        return SandboxRunResult(action_json=action_json, blocked_egress_attempts=self.simulate_blocked_hosts)
