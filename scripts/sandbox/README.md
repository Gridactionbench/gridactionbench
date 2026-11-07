# Agent execution sandbox — infrastructure

See `docs/architecture/adr/ADR-019-agent-execution-sandbox.md` for the full decision
record and threat model this exists to address. This directory holds the infrastructure
`gridactionbench/agents/docker_backend.py::DockerSandboxBackend` assumes already exists —
it is **not** provisioned automatically by the Python code, since it is real,
longer-lived infrastructure (a Docker network + a running proxy container), not
something to spin up fresh on every agent decision.

**Honesty note:** everything in this directory is written against Docker's and Squid's
documented behaviour as carefully as possible, but has not been built or run against a
real Docker host in this project's own development environment (no Docker is installed
here). Validate it against your own Docker host before relying on it for a real
Verified-tier run — see `docs/architecture/adr/ADR-019-agent-execution-sandbox.md`'s own
honesty note for the same caveat applied to the Python adapter code.

## What gets provisioned, and why

Two trust tiers map to two different setups:

- **No model-provider API call needed at all** (the agent is e.g. a local rule-based
  policy someone submitted, or an LLM call is proxied in some other way entirely outside
  this sandbox). Use `DockerSandboxBackend(image=...)` with no `egress_network` —
  `SandboxConfig.allowed_hosts` stays empty (the default), and the backend runs the
  container with `--network none`: no network interface at all, full stop. **This is the
  default and the strongest policy** — prefer it whenever the agent doesn't need to make
  its own outbound calls.
- **The agent genuinely needs to call its own model provider's API from inside the
  sandbox** (the realistic case for any actual LLM-backed submission — the whole point of
  sandboxing is that the model call itself happens inside the isolated boundary, not
  pulled out into trusted harness code). Run `provision_network.sh` once per set of
  allowed hosts, then pass the resulting network/proxy container names to
  `DockerSandboxBackend`.

## Provisioning the egress-restricted network

```bash
scripts/sandbox/provision_network.sh gab-sandbox-net gab-egress-proxy api.anthropic.com
```

This builds a minimal Squid image (`egress_proxy/Dockerfile` +
`egress_proxy/squid.conf.template`, allowlist baked in from the arguments — never a
default-open list), creates an `--internal` Docker network (no route to the outside world
at all except through whatever else is attached to it), and starts the proxy container
attached to both that internal network and Docker's normal bridge network (so it alone
has a real route out, and relays only allowlisted `CONNECT` requests through).

Then:

```python
from gridactionbench.agents.docker_backend import DockerSandboxBackend

backend = DockerSandboxBackend(
    image="my-llm-agent:latest",
    egress_network="gab-sandbox-net",
    egress_proxy_container="gab-egress-proxy",
)
```

## Why a sandboxed agent can't bypass this by ignoring the proxy

Two independent layers, not one:

1. **The network itself has no outbound route** (`docker network create --internal`) —
   an agent container attached to it literally cannot open a socket to anything outside
   that network except the proxy container, regardless of whether its own code respects
   `HTTPS_PROXY`/`HTTP_PROXY` or not. This is the real enforcement boundary.
2. **The proxy only tunnels `CONNECT` to allowlisted hostnames** (`squid.conf.template`'s
   `dstdomain` ACL) — a cooperative agent is pointed at it via the `HTTPS_PROXY` env var
   `DockerSandboxBackend` sets automatically; this is a convenience for well-behaved
   agents, not itself the enforcement boundary (layer 1 is).

A denied `CONNECT` attempt is logged by Squid and surfaced back to the harness as a
`SandboxIncident` (`gridactionbench/agents/sandboxed.py`) via
`DockerSandboxBackend._blocked_egress_since`, which queries the proxy container's own log
for the time window of that one invocation (`docker logs --since/--until`) — see that
method's docstring for the exact log-format assumption, and
`tests/unit/test_sandboxed_agent.py::test_parse_squid_denied_hosts_extracts_denied_connect_targets`
for what it parses.

## What this does not do

- It does not decrypt or inspect the content of an allowed HTTPS connection — Squid here
  only tunnels `CONNECT`, it never terminates TLS (no `SslBump`), so a model-provider
  conversation stays end-to-end encrypted exactly as if there were no proxy. This
  sandbox's job is restricting *which hosts* an agent can reach, not inspecting what it
  sends them.
- It does not detect an agent encoding scenario content *within* an otherwise-legitimate
  request to an allowed host (e.g. smuggling held-out scenario text inside a prompt sent
  to its own model provider, who may itself retain logs). That residual risk is
  explicitly named as an open limitation in
  `docs/architecture/adr/ADR-019-agent-execution-sandbox.md`'s Consequences section, not
  solved here.
