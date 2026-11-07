"""SandboxedAgentAdapter — runs an untrusted agent (LLM-backed, tool-using, or any
third-party submission) inside an isolated sandbox instead of in-process.

See docs/architecture/adr/ADR-019-agent-execution-sandbox.md for the full decision record.
Implements the existing `AgentAdapter` protocol (gridactionbench/agents/base.py) —
`gridactionbench/runners/single_step.py` calls this exactly the same way it calls any
in-process reference agent (`agent.act(observation) -> action`); no harness code changes
were needed, since that was already the only crossing point.

Trust boundary: only `EnergyObservationV1` (serialized to JSON) ever crosses into the
sandbox, and only `AgentActionV1` JSON ever crosses back out — there is no "mount a host
path" option anywhere in this module, deliberately, so there is nothing for a
misconfiguration to accidentally expose. The `Scenario`/`Oracle` object is never
constructed in a form the sandboxed process could reach, and the private holdout seed
(`gridactionbench/holdouts/private_seed.py`) can never end up in a sandbox's environment —
`SandboxConfig` enforces that itself, independent of which backend runs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from gridactionbench.schemas.action import AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1

# Environment variable families that must never be visible inside an agent sandbox,
# regardless of what an operator's own `env` dict declares at construction time — the
# private holdout seed foremost among them. Matched by prefix so the whole
# GRIDACTIONBENCH_PRIVATE_* family is covered, not just today's one exact name.
FORBIDDEN_ENV_PREFIXES = ("GRIDACTIONBENCH_PRIVATE_",)


class SandboxForbiddenConfigError(ValueError):
    """Raised when a SandboxConfig would have exposed a forbidden secret to the sandbox."""


@dataclass(frozen=True)
class SandboxConfig:
    """Everything a sandbox backend needs to run one agent invocation, and nothing else.

    No field here can reference the host filesystem outside this one observation/action
    exchange — there is deliberately no "mount path" field at all (ADR-019): the
    observation crosses in via stdin, the action crosses out via stdout, full stop.
    `allowed_hosts` empty (the default) means no network egress at all — the strongest,
    and default, policy.
    """

    allowed_hosts: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    memory_limit_mb: int = 512
    cpu_limit: float = 1.0
    pids_limit: int = 64

    def __post_init__(self) -> None:
        for key in self.env:
            if any(key.startswith(prefix) for prefix in FORBIDDEN_ENV_PREFIXES):
                raise SandboxForbiddenConfigError(
                    f"refusing to build a SandboxConfig that would expose {key!r} to a "
                    "sandboxed agent process"
                )


@dataclass(frozen=True)
class SandboxRunResult:
    action_json: str
    # Hostnames the egress proxy observed and blocked during this one invocation — see
    # docs/architecture/adr/ADR-019-agent-execution-sandbox.md and
    # scripts/sandbox/README.md for how a real backend populates this.
    blocked_egress_attempts: tuple[str, ...] = ()


class SandboxBackend(Protocol):
    def run(self, observation_json: str, config: SandboxConfig) -> SandboxRunResult: ...


class SandboxIncident(RuntimeError):
    """A sandboxed agent attempted network egress beyond its allowlist. Must be logged as
    a scenario-integrity incident, not silently swallowed — this is the concrete
    mechanism that closes docs/benchmark/THREAT_MODEL.md's 'Hidden-set extraction' and
    'Malicious tool output' rows instead of leaving them as 'out of our control.'"""


class SandboxedAgentAdapter:
    """Implements AgentAdapter by delegating to an isolated `SandboxBackend`.

    `agent_type` is always "sandboxed" regardless of what runs inside — from the
    harness's perspective the defining property is the isolation boundary, not the
    wrapped agent's own architecture (that detail belongs in the wrapped agent's own
    disclosed configuration, per docs/benchmark/SUBMISSION_RULES.md).
    """

    agent_type = "sandboxed"

    def __init__(
        self,
        backend: SandboxBackend,
        agent_id: str,
        agent_version: str,
        allowed_hosts: tuple[str, ...] = (),
        env: Optional[dict[str, str]] = None,
        on_incident: Optional[Callable[[SandboxIncident], None]] = None,
        **config_overrides,
    ) -> None:
        self.backend = backend
        self.agent_id = agent_id
        self.agent_version = agent_version
        self._on_incident = on_incident
        # Constructing SandboxConfig here (not lazily inside act()) means a forbidden env
        # var is rejected at adapter-construction time, not silently deferred until the
        # first scenario happens to run.
        self._config = SandboxConfig(allowed_hosts=allowed_hosts, env=dict(env or {}), **config_overrides)

    def act(self, observation: EnergyObservationV1) -> AgentActionV1:
        observation_json = observation.model_dump_json()
        result = self.backend.run(observation_json, self._config)
        if result.blocked_egress_attempts:
            incident = SandboxIncident(
                f"{self.agent_id} attempted egress to disallowed host(s): "
                f"{', '.join(result.blocked_egress_attempts)}"
            )
            if self._on_incident is not None:
                self._on_incident(incident)
            else:
                # Never silently dropped by default — see SandboxIncident's docstring.
                # A caller that wants to keep a run going despite incidents must opt in
                # explicitly via on_incident, not get that behaviour for free.
                raise incident
        # Malformed/schema-violating output is handled by letting pydantic's
        # ValidationError propagate — single_step.py already catches any exception from
        # agent.act() and records it as a schema-invalid, non-crashing outcome
        # (docs/architecture/adr/ADR-008-structured-agent-output.md), the same path a
        # misbehaving in-process agent already goes through today.
        return AgentActionV1.model_validate_json(result.action_json)
