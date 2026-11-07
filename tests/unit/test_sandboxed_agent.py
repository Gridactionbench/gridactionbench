"""Unit tests for SandboxedAgentAdapter (gridactionbench/agents/sandboxed.py) and
DockerSandboxBackend (gridactionbench/agents/docker_backend.py).

See docs/architecture/adr/ADR-019-agent-execution-sandbox.md. These tests prove the
adapter's own orchestration logic (never exposing the private seed, raising on blocked
egress by default, validating returned JSON) using the fake backend
(tests/fakes/fake_sandbox_backend.py) — they do not and cannot prove real OS-level
isolation, since no Docker daemon exists in this environment; see that fake's own
docstring and DockerSandboxBackend's for the honesty note this implies.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gridactionbench.agents.docker_backend import (
    DockerSandboxBackend,
    SandboxBackendError,
    _parse_squid_denied_hosts,
)
from gridactionbench.agents.sandboxed import (
    SandboxConfig,
    SandboxedAgentAdapter,
    SandboxForbiddenConfigError,
    SandboxIncident,
)
from gridactionbench.schemas.action import ActionType, AgentActionV1
from gridactionbench.schemas.observation import EnergyObservationV1
from tests.fakes.fake_sandbox_backend import FakeSandboxBackend


def make_observation() -> EnergyObservationV1:
    return EnergyObservationV1(
        benchmark_version="0.1.0",
        suite_version="0.2.0",
        scenario_id="TEST",
        timestamp=datetime.now(timezone.utc),
        network_model={
            "buses": [
                {"bus_id": 1, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
                {"bus_id": 2, "voltage_pu": 1.0, "voltage_min_pu": 0.5, "voltage_max_pu": 1.5},
            ],
            "branches": [
                {"branch_id": "L1", "from_bus": 1, "to_bus": 2, "mva_flow": 10.0, "mva_limit": 1000.0, "sensitivity_mva_per_mw": 1.0}
            ],
            "generators": [
                {
                    "bus_id": 2, "mw_output": 10.0, "mw_min": 0.0, "mw_max": 20.0,
                    "mw_ramp_up_limit_per_step": 20.0, "mw_ramp_down_limit_per_step": 20.0,
                    "voltage_sensitivity_pu_per_mw": 0.01,
                }
            ],
        },
    )


def _idle_agent_fn(observation_json: str) -> str:
    del observation_json
    return AgentActionV1(action=ActionType.IDLE).model_dump_json()


# --- SandboxConfig: the private-seed exclusion is enforced at the config layer, not left
# to each backend to remember ---


def test_sandbox_config_rejects_forbidden_env_prefix():
    with pytest.raises(SandboxForbiddenConfigError):
        SandboxConfig(env={"GRIDACTIONBENCH_PRIVATE_SEED": "155333560"})


def test_sandbox_config_accepts_ordinary_env():
    config = SandboxConfig(env={"ANTHROPIC_API_KEY": "sk-test"}, allowed_hosts=("api.anthropic.com",))
    assert config.env == {"ANTHROPIC_API_KEY": "sk-test"}


def test_sandboxed_agent_adapter_never_exposes_private_seed_even_if_caller_tries():
    backend = FakeSandboxBackend(_idle_agent_fn)
    with pytest.raises(SandboxForbiddenConfigError):
        SandboxedAgentAdapter(
            backend=backend,
            agent_id="test-llm-agent",
            agent_version="0.1.0",
            env={"GRIDACTIONBENCH_PRIVATE_SEED": "155333560"},
        )
    # And critically: the backend was never even invoked — rejected at construction time.
    assert backend.calls == []


# --- Round trip through the fake backend ---


def test_sandboxed_agent_adapter_returns_valid_action_via_fake_backend():
    backend = FakeSandboxBackend(_idle_agent_fn)
    agent = SandboxedAgentAdapter(backend=backend, agent_id="test-llm-agent", agent_version="0.1.0")
    action = agent.act(make_observation())
    assert action.action is ActionType.IDLE
    assert agent.agent_type == "sandboxed"
    assert len(backend.calls) == 1


def test_sandboxed_agent_adapter_raises_on_malformed_action_json():
    backend = FakeSandboxBackend(lambda obs_json: "not valid json at all")
    agent = SandboxedAgentAdapter(backend=backend, agent_id="broken-agent", agent_version="0.1.0")
    with pytest.raises(Exception):  # pydantic's ValidationError — propagates, matching single_step.py's existing catch-all
        agent.act(make_observation())


# --- Blocked-egress handling: never silently dropped by default ---


def test_sandboxed_agent_adapter_raises_on_blocked_egress_by_default():
    backend = FakeSandboxBackend(_idle_agent_fn)
    backend.simulate_blocked_hosts = ("evil.example.com",)
    agent = SandboxedAgentAdapter(backend=backend, agent_id="test-llm-agent", agent_version="0.1.0")
    with pytest.raises(SandboxIncident, match="evil.example.com"):
        agent.act(make_observation())


def test_sandboxed_agent_adapter_calls_incident_callback_instead_of_raising_when_provided():
    backend = FakeSandboxBackend(_idle_agent_fn)
    backend.simulate_blocked_hosts = ("evil.example.com",)
    captured: list[SandboxIncident] = []
    agent = SandboxedAgentAdapter(
        backend=backend, agent_id="test-llm-agent", agent_version="0.1.0", on_incident=captured.append
    )
    action = agent.act(make_observation())  # must not raise — callback opted in
    assert action.action is ActionType.IDLE
    assert len(captured) == 1
    assert "evil.example.com" in str(captured[0])


# --- DockerSandboxBackend: the parts testable without a real Docker daemon ---


def test_docker_backend_raises_cleanly_when_docker_is_not_installed(monkeypatch):
    monkeypatch.setattr("gridactionbench.agents.docker_backend.shutil.which", lambda name: None)
    # Force this path even on CI hosts with Docker installed.
    backend = DockerSandboxBackend(image="example/agent:latest")
    with pytest.raises(SandboxBackendError, match="docker is not installed"):
        backend.run(AgentActionV1(action=ActionType.IDLE).model_dump_json(), SandboxConfig())


def test_docker_backend_refuses_ambiguous_network_policy():
    backend = DockerSandboxBackend(image="example/agent:latest", egress_network=None)
    config = SandboxConfig(allowed_hosts=("api.anthropic.com",))
    with pytest.raises(SandboxBackendError, match="egress_network"):
        backend.run("{}", config)


# --- Squid access-log parsing: pure logic, fully testable without a real proxy ---


def test_parse_squid_denied_hosts_extracts_denied_connect_targets():
    log = (
        "1699999999.123    12 172.18.0.5 TCP_DENIED/403 3985 CONNECT evil.example.com:443 - HIER_NONE/- -\n"
        "1699999999.456     8 172.18.0.5 TCP_TUNNEL/200 5102 CONNECT api.anthropic.com:443 - HIER_DIRECT/1.2.3.4 -\n"
    )
    assert _parse_squid_denied_hosts(log) == ("evil.example.com",)


def test_parse_squid_denied_hosts_ignores_malformed_or_short_lines():
    assert _parse_squid_denied_hosts("garbage\nnot a log line\n") == ()
    assert _parse_squid_denied_hosts("") == ()
