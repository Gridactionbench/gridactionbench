"""Docker orchestration tests with no daemon, plus real bounded subprocess checks."""
import subprocess
import sys
from unittest.mock import Mock

import pytest

from gridactionbench.agents import docker_backend as module
from gridactionbench.agents.docker_backend import DockerSandboxBackend, SandboxBackendError
from gridactionbench.agents.docker_process import run_bounded, DockerProcessError
from gridactionbench.agents.proxy_policy import render_proxy_config
from gridactionbench.agents.sandboxed import SandboxConfig, SandboxForbiddenConfigError


@pytest.mark.parametrize("kwargs", [
    {"timeout_seconds": -1}, {"timeout_seconds": float("nan")},
    {"cpu_limit": 0}, {"memory_limit_mb": 0}, {"pids_limit": -1},
    {"max_output_bytes": 0}, {"max_output_bytes": 17 * 1024 * 1024},
    {"env": {"HTTPS_PROXY": "http://other"}},
    {"allowed_hosts": (".example.com",)}, {"allowed_hosts": ("127.0.0.1",)},
    {"allowed_hosts": ("example.com\nhttp_access allow all",)},
])
def test_invalid_sandbox_configuration_is_rejected(kwargs):
    with pytest.raises(SandboxForbiddenConfigError):
        SandboxConfig(**kwargs)


def test_environment_is_copied_and_immutable():
    original = {"TEST_KEY": "test"}
    config = SandboxConfig(env=original)
    original["GRIDACTIONBENCH_PRIVATE_SEED"] = "test"
    assert "GRIDACTIONBENCH_PRIVATE_SEED" not in config.env
    with pytest.raises(TypeError):
        config.env["GRIDACTIONBENCH_PRIVATE_SEED"] = "test"


def test_process_output_is_bounded():
    with pytest.raises(DockerProcessError, match="output byte limit"):
        run_bounded([sys.executable, "-c", "import sys; sys.stdout.write('x'*1000000)"], max_output_bytes=1024)


def test_process_timeout_terminates_the_client():
    with pytest.raises(DockerProcessError, match="timed out"):
        run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)


def test_process_drains_both_streams_and_feeds_stdin():
    result = run_bounded([sys.executable, "-c",
        "import sys; s=sys.stdin.read(); print(s); print('error',file=sys.stderr)"], input_text="observation")
    assert result.stdout.strip() == "observation"
    assert result.stderr.strip() == "error"


@pytest.mark.parametrize("failure", ["Docker command timed out", "Docker command exceeded its output byte limit"])
def test_agent_failure_always_attempts_container_cleanup(monkeypatch, failure):
    monkeypatch.setattr(module, "_require_docker", lambda: "docker")
    def command(cmd, **kwargs):
        if cmd[1] == "start":
            raise DockerProcessError(failure)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    run = Mock(side_effect=command)
    monkeypatch.setattr(module, "run_bounded", run)
    monkeypatch.setattr(DockerSandboxBackend, "_inspect", lambda *a: {"Config": {}})
    with pytest.raises(SandboxBackendError, match=failure):
        DockerSandboxBackend("test-agent").run("{}", SandboxConfig())
    assert run.call_args.args[0][1:3] == ["rm", "--force"]


def test_missing_proxy_is_rejected_before_docker(monkeypatch):
    with pytest.raises(SandboxBackendError, match="egress_proxy_container"):
        DockerSandboxBackend("test-agent", "network").run("{}", SandboxConfig(allowed_hosts=("example.com",)))


def test_unrestricted_blueprint_network_is_rejected(monkeypatch):
    backend = DockerSandboxBackend("test-agent", "network", "proxy")
    monkeypatch.setattr(backend, "_inspect", lambda *a: {"Internal": False, "State": {"Running": True}})
    with pytest.raises(SandboxBackendError, match="internal bridge"):
        backend._blueprint_image("docker", SandboxConfig(allowed_hosts=("example.com",)))


def test_mismatched_allowlist_is_rejected(monkeypatch):
    backend = DockerSandboxBackend("test-agent")
    monkeypatch.setattr(backend, "_checked", lambda *a: render_proxy_config(("other.example.com",)))
    with pytest.raises(SandboxBackendError, match="allowlist"):
        backend._verify_policy("docker", "proxy", SandboxConfig(allowed_hosts=("example.com",)))


def test_log_failure_is_explicit(monkeypatch):
    backend = DockerSandboxBackend("test-agent")
    monkeypatch.setattr(module, "run_bounded", lambda *a, **k: subprocess.CompletedProcess([], 1, "", "failure"))
    with pytest.raises(SandboxBackendError):
        backend._checked("docker", ["logs", "proxy"])
    with pytest.raises(SandboxBackendError, match="log format"):
        module._parse_squid_denied_hosts("unexpected log", strict=True)


def test_networked_run_uses_fresh_resources_and_cleans_in_reverse_order(monkeypatch):
    monkeypatch.setattr(module, "_require_docker", lambda: "docker")
    backend = DockerSandboxBackend("test-agent", "blueprint-network", "blueprint-proxy")
    monkeypatch.setattr(backend, "_blueprint_image", lambda *a: "sha256:" + "a" * 64)
    monkeypatch.setattr(backend, "_verify_policy", lambda *a: None)
    monkeypatch.setattr(backend, "_inspect", lambda *a: {"State": {"Running": True}})
    checked = Mock(return_value="")
    monkeypatch.setattr(backend, "_checked", checked)
    monkeypatch.setattr(backend, "_command", Mock(return_value=subprocess.CompletedProcess([], 0, "{}", "")))
    removed = Mock()
    monkeypatch.setattr(backend, "_remove", removed)
    backend.run("{}", SandboxConfig(allowed_hosts=("example.com",)))
    names = [call.args[2] for call in removed.call_args_list]
    assert names[0].startswith("gab-agent-")
    assert names[1].startswith("gab-proxy-")
    assert names[2].startswith("gab-net-")
    assert "blueprint-network" not in names


def test_cleanup_failure_cannot_return_success(monkeypatch):
    monkeypatch.setattr(module, "_require_docker", lambda: "docker")
    backend = DockerSandboxBackend("test-agent")
    monkeypatch.setattr(backend, "_inspect", lambda *a: {"Config": {}})
    monkeypatch.setattr(backend, "_command", Mock(return_value=subprocess.CompletedProcess([], 0, "{}", "")))
    monkeypatch.setattr(backend, "_remove", Mock(side_effect=SandboxBackendError("cleanup failed")))
    with pytest.raises(SandboxBackendError, match="cleanup failed"):
        backend.run("{}", SandboxConfig())


def test_image_declared_volumes_are_rejected(monkeypatch):
    monkeypatch.setattr(module, "_require_docker", lambda: "docker")
    backend = DockerSandboxBackend("test-agent")
    monkeypatch.setattr(backend, "_inspect", lambda *a: {"Config": {"Volumes": {"/data": {}}}})
    with pytest.raises(SandboxBackendError, match="volumes"):
        backend.run("{}", SandboxConfig())


def test_partial_network_setup_failure_cleans_created_resources(monkeypatch):
    monkeypatch.setattr(module, "_require_docker", lambda: "docker")
    backend = DockerSandboxBackend("test-agent", "blueprint-network", "blueprint-proxy")
    monkeypatch.setattr(backend, "_inspect", lambda *a: {"Config": {}})
    monkeypatch.setattr(backend, "_blueprint_image", lambda *a: "sha256:" + "a" * 64)
    def checked(docker, args, **kwargs):
        if args[0] == "run":
            raise SandboxBackendError("proxy startup failed")
        return ""
    monkeypatch.setattr(backend, "_checked", checked)
    removed = Mock()
    monkeypatch.setattr(backend, "_remove", removed)
    with pytest.raises(SandboxBackendError, match="proxy startup failed"):
        backend.run("{}", SandboxConfig(allowed_hosts=("example.com",)))
    assert [call.args[1] for call in removed.call_args_list] == ["container", "network"]
