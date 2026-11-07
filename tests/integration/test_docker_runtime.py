"""Opt-in checks against real Docker. These never run on default unit-test jobs."""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from gridactionbench.agents.docker_backend import DockerSandboxBackend, SandboxBackendError
from gridactionbench.agents.sandboxed import SandboxConfig

IMAGE = os.environ.get("GRIDACTIONBENCH_DOCKER_TEST_IMAGE")
pytestmark = [pytest.mark.docker, pytest.mark.skipif(not IMAGE, reason="set GRIDACTIONBENCH_DOCKER_TEST_IMAGE")]


def resources():
    containers = subprocess.run(["docker", "ps", "-a", "--filter", "name=gab-", "--format", "{{.Names}}"],
                                capture_output=True, text=True, check=True).stdout.splitlines()
    networks = subprocess.run(["docker", "network", "ls", "--filter", "name=gab-net-", "--format", "{{.Name}}"],
                              capture_output=True, text=True, check=True).stdout.splitlines()
    return set(containers), set(networks)


@pytest.mark.parametrize("mode", ["idle", "timeout", "flood"])
def test_runtime_limits_and_cleanup(mode):
    before = resources()
    backend = DockerSandboxBackend(IMAGE)
    config = SandboxConfig(timeout_seconds=2, max_output_bytes=1024, env={"GAB_TEST_MODE": mode})
    if mode == "idle":
        assert json.loads(backend.run("{}", config).action_json) == {"action": "IDLE"}
    else:
        with pytest.raises(SandboxBackendError):
            backend.run("{}", config)
    assert resources() == before


def test_concurrent_offline_agents_do_not_leave_resources():
    before = resources()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: DockerSandboxBackend(IMAGE).run("{}", SandboxConfig()), range(2)))
    assert all(json.loads(result.action_json) == {"action": "IDLE"} for result in results)
    assert resources() == before


def test_networked_agents_have_separate_proxies_and_denied_egress():
    network = os.environ.get("GRIDACTIONBENCH_TEST_EGRESS_NETWORK")
    proxy = os.environ.get("GRIDACTIONBENCH_TEST_EGRESS_PROXY")
    if not network or not proxy:
        pytest.skip("requires an example.com proxy blueprint; see scripts/sandbox/README.md")
    before = resources()
    backend = DockerSandboxBackend(IMAGE, network, proxy)
    def run(_):
        return backend.run("{}", SandboxConfig(allowed_hosts=("example.com",),
            timeout_seconds=15, env={"GAB_TEST_MODE": "network"}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    for result in results:
        assert json.loads(result.action_json) == {"direct_blocked": True, "proxy_denied": True}
        assert result.blocked_egress_attempts == ("example.com",)
    assert resources() == before
