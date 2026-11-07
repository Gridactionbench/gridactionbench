# Agent sandbox setup

The Docker backend is experimental. Its default is no network access. Run untrusted
submissions only after validating isolation on a dedicated host; see
[the runtime release gates](../../docs/testing/RUNTIME_VALIDATION.md).

## Offline execution

Build or pull an agent image explicitly before handing it to the harness. The backend
uses `--pull never`, rejects image-declared writable volumes, mounts no host paths,
and runs as UID/GID 65532 with a read-only root filesystem and a 64 MiB `/tmp`.
Images must support that user. Only observation JSON and explicitly configured
agent environment variables enter the container. Use scoped, budget-limited provider
credentials; the submitted agent can read any key explicitly supplied to it.

Stdout/stderr share a configurable byte limit (256 KiB by default). CPU, memory,
process count, and wall-clock limits must be positive. Containers are explicitly
removed after success, timeout, output overflow, or other failure. A cleanup failure
invalidates the invocation and names resources that require operator attention.
Docker daemon access remains trusted administrative access.

## Networked execution

Provision a trusted proxy blueprint from an active project environment:

```bash
bash scripts/sandbox/provision_network.sh gab-test-blueprint gab-test-proxy example.com
```

The script requires Python, Bash, and a Linux Docker host. It validates exact DNS
hostnames and renders the canonical policy from
`gridactionbench/agents/proxy_policy.py`. It refuses existing resource names rather
than replacing or silently reusing another network or container. Check proxy startup
with `docker logs gab-test-proxy` before evaluating agents.

```python
from gridactionbench.agents.docker_backend import DockerSandboxBackend
from gridactionbench.agents.sandboxed import SandboxConfig

backend = DockerSandboxBackend(
    image="my-agent:reviewed",
    egress_network="gab-test-blueprint",
    egress_proxy_container="gab-test-proxy",
)
config = SandboxConfig(allowed_hosts=("example.com",))
```

The blueprint must be an internal bridge containing only its running, unmounted
proxy. The backend checks the proxy configuration against the declared allowlist
and asks Squid to parse it. Every invocation then gets a fresh internal network and
a new proxy created from the blueprint's immutable image ID. The new proxy is also
attached to Docker's bridge for outbound traffic. Agents never join the shared
blueprint network, and per-invocation logs cannot mix concurrent agents' requests.

Only CONNECT to declared hostnames on port 443 is permitted. Private destination
addresses are denied. Proxy configuration cannot be overridden through `config.env`.
Unavailable, malformed, or excessive proxy logs invalidate the invocation. All
per-invocation resources are removed in reverse order, including after failure.
Blueprint resources remain under operator control and are not deleted by the backend.

The backend assumes a trusted blueprint image and Docker administrator. It does not
inspect TLS contents or stop scenario data being sent to an allowed model provider.
Validate DNS, IPv6, host-service and peer-container isolation on the deployment host;
a hostname allowlist alone does not establish those properties. Networked execution
adds a proxy/container startup cost to each action. No real Docker validation has
been completed in this project's implementation environment.

## Tests

The repository-owned test agent has normal, timeout, output-flood, and network-probe
modes. Follow [runtime validation](../../docs/testing/RUNTIME_VALIDATION.md) to run
these on a disposable Docker host. Dockerfiles use maintained base-image tags for
local testing; record immutable image IDs/digests for reproducible evaluation runs.
