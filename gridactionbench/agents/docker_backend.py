"""Experimental Docker isolation; validate with a real daemon before untrusted use.

Each invocation has a unique container name. Networked runs clone a verified proxy
blueprint into a fresh internal network; no agent network or proxy logs are shared.
Only observations and explicitly configured environment variables enter the agent.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid

from gridactionbench.agents.docker_process import DockerProcessError, run_bounded
from gridactionbench.agents.proxy_policy import normalized_policy, render_proxy_config
from gridactionbench.agents.sandboxed import SandboxConfig, SandboxRunResult

NO_NETWORK = "none"


class SandboxBackendError(RuntimeError):
    """Execution or isolation could not be established; this run is not verified."""


def _require_docker() -> str:
    path = shutil.which("docker")
    if path is None:
        raise SandboxBackendError("docker is not installed or not on PATH")
    return path


class DockerSandboxBackend:
    """Run an agent in fresh resources and explicitly clean up every exit path.

    For networked runs, egress_network and egress_proxy_container identify a trusted
    blueprint provisioned by scripts/sandbox/provision_network.sh. The blueprint's
    running proxy must contain the canonical policy matching config.allowed_hosts.
    The agent never joins that shared blueprint network.
    """

    def __init__(self, image: str, egress_network: str | None = None,
                 egress_proxy_container: str | None = None):
        if not image or image.startswith("-") or "\0" in image or any(c.isspace() for c in image):
            raise SandboxBackendError("image must be a non-option Docker image reference")
        for name in (egress_network, egress_proxy_container):
            if name is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
                raise SandboxBackendError("invalid Docker resource name")
        self.image = image
        self.egress_network = egress_network
        self.egress_proxy_container = egress_proxy_container

    @staticmethod
    def _command(docker: str, args: list[str], **kwargs):
        try:
            return run_bounded([docker, *args], **kwargs)
        except DockerProcessError as exc:
            raise SandboxBackendError(str(exc)) from exc

    def _checked(self, docker: str, args: list[str], **kwargs) -> str:
        result = self._command(docker, args, **kwargs)
        if result.returncode:
            # Do not persist arbitrary container stderr, which can include credentials.
            raise SandboxBackendError(f"Docker {args[0]} failed (exit {result.returncode})")
        return result.stdout

    def _inspect(self, docker: str, kind: str, name: str) -> dict:
        try:
            result = json.loads(self._checked(docker, [kind, "inspect", name]))
            if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
                raise ValueError
            return result[0]
        except (ValueError, TypeError) as exc:
            raise SandboxBackendError("invalid Docker inspect response") from exc

    def _verify_policy(self, docker: str, proxy: str, config: SandboxConfig) -> None:
        actual = self._checked(docker, ["exec", proxy, "cat", "/etc/squid/squid.conf"])
        if normalized_policy(actual) != normalized_policy(render_proxy_config(config.allowed_hosts)):
            raise SandboxBackendError("proxy policy does not match the declared allowlist")
        self._checked(docker, ["exec", proxy, "squid", "-k", "parse"])

    def _blueprint_image(self, docker: str, config: SandboxConfig) -> str:
        network = self._inspect(docker, "network", self.egress_network)
        proxy = self._inspect(docker, "container", self.egress_proxy_container)
        if network.get("Internal") is not True or network.get("Driver") != "bridge":
            raise SandboxBackendError("egress_network must be an internal bridge")
        if set(network.get("Containers", {})) != {proxy.get("Id")}:
            raise SandboxBackendError("blueprint network must contain only its proxy")
        mounts = proxy.get("Mounts", [])
        if proxy.get("State", {}).get("Running") is not True or any(
            m.get("Type") != "tmpfs" or m.get("Destination") != "/tmp" for m in mounts
        ):
            raise SandboxBackendError("proxy blueprint must be running without host/volume mounts")
        self._verify_policy(docker, self.egress_proxy_container, config)
        image = proxy.get("Image", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise SandboxBackendError("proxy blueprint has no immutable image ID")
        return image

    def _wait_for_proxy(self, docker: str, proxy: str) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self._command(docker, ["exec", proxy, "squid", "-k", "check"], timeout=1)
            if result.returncode == 0:
                return
            time.sleep(0.1)
        raise SandboxBackendError("proxy did not become ready")

    def _remove(self, docker: str, kind: str, name: str) -> None:
        args = ["rm", "--force", "--volumes", name] if kind == "container" else ["network", "rm", name]
        result = self._command(docker, args)
        missing = "No such container" if kind == "container" else "not found"
        if result.returncode and missing not in result.stderr and "No such network" not in result.stderr:
            raise SandboxBackendError(f"could not remove {kind} {name}; operator cleanup required")

    def run(self, observation_json: str, config: SandboxConfig) -> SandboxRunResult:
        if config.allowed_hosts and not self.egress_network:
            raise SandboxBackendError("allowed_hosts requires egress_network")
        if config.allowed_hosts and not self.egress_proxy_container:
            raise SandboxBackendError("allowed_hosts requires egress_proxy_container")
        docker = _require_docker()
        image_info = self._inspect(docker, "image", self.image)
        if image_info.get("Config", {}).get("Volumes"):
            raise SandboxBackendError("agent images must not declare writable Docker volumes")
        suffix = uuid.uuid4().hex
        agent = "gab-agent-" + suffix
        proxy = "gab-proxy-" + suffix
        network = "gab-net-" + suffix if config.allowed_hosts else NO_NETWORK
        resources = []
        try:
            if config.allowed_hosts:
                image = self._blueprint_image(docker, config)
                resources.append(("network", network))
                self._checked(docker, ["network", "create", "--driver", "bridge", "--internal", network])
                resources.append(("container", proxy))
                self._checked(docker, ["run", "--detach", "--name", proxy, "--network", "bridge",
                    "--read-only", "--tmpfs", "/tmp:rw,size=16m", "--memory", "128m",
                    "--cpus", "0.5", "--pids-limit", "64", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges", "--user", "65532:65532",
                    "--log-driver", "local", "--log-opt", "max-size=1m", "--log-opt", "max-file=2", image])
                self._checked(docker, ["network", "connect", network, proxy])
                self._verify_policy(docker, proxy, config)
                self._wait_for_proxy(docker, proxy)

            cmd = ["create", "--pull", "never", "--name", agent, "-i", "--network", network,
                "--dns", "127.0.0.1",
                "--read-only", "--tmpfs", "/tmp:rw,size=64m", "--memory", f"{config.memory_limit_mb}m",
                "--memory-swap", f"{config.memory_limit_mb}m", "--cpus", str(config.cpu_limit),
                "--pids-limit", str(config.pids_limit), "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL", "--user", "65532:65532", "--log-driver", "none"]
            if config.allowed_hosts:
                proxy_url = f"http://{proxy}:3128"
                cmd += ["-e", f"HTTPS_PROXY={proxy_url}", "-e", f"HTTP_PROXY={proxy_url}"]
            for key, value in config.env.items():
                cmd += ["-e", f"{key}={value}"]
            cmd.append(self.image)
            resources.append(("container", agent))
            # Establish container identity before running untrusted code. A start timeout
            # can then remove a known-created container, rather than racing docker run.
            self._checked(docker, cmd)
            completed = self._command(docker, ["start", "--attach", "--interactive", agent], input_text=observation_json,
                timeout=config.timeout_seconds, max_output_bytes=config.max_output_bytes)
            blocked = ()
            if config.allowed_hosts:
                state = self._inspect(docker, "container", proxy)
                if state.get("State", {}).get("Running") is not True:
                    raise SandboxBackendError("egress monitoring proxy stopped during the run")
                # This proxy belongs only to this invocation, including failed agent runs.
                log = self._checked(docker, ["logs", proxy])
                blocked = _parse_squid_denied_hosts(log, strict=True)
            if completed.returncode:
                raise SandboxBackendError(f"sandboxed agent exited {completed.returncode}")
            return SandboxRunResult(action_json=completed.stdout.strip(), blocked_egress_attempts=blocked)
        finally:
            failures = []
            for kind, name in reversed(resources):
                try:
                    self._remove(docker, kind, name)
                except SandboxBackendError as exc:
                    failures.append(str(exc))
            if failures:
                raise SandboxBackendError("; ".join(failures))


def _parse_squid_denied_hosts(proxy_log: str, *, strict: bool = False) -> tuple[str, ...]:
    """Parse canonical Squid access.log; fail explicitly on unrecognized nonempty logs."""
    hosts = []
    for line in proxy_log.splitlines():
        fields = line.split()
        valid = len(fields) >= 7 and fields[0].replace(".", "", 1).isdigit() and "/" in fields[3]
        if not valid:
            if strict and line.strip():
                raise SandboxBackendError("unrecognized proxy access log format")
            continue
        if "TCP_DENIED" in fields[3] and fields[5] == "CONNECT":
            hosts.append(fields[6].rsplit(":", 1)[0])
    return tuple(hosts)
