#!/usr/bin/env bash
# Provisions the Docker network + allowlisting egress proxy that
# gridactionbench/agents/docker_backend.py::DockerSandboxBackend attaches sandboxed
# agent containers to whenever a SandboxConfig declares a non-empty `allowed_hosts`.
# See docs/architecture/adr/ADR-019-agent-execution-sandbox.md.
#
# This is shared, longer-lived infrastructure — provisioned once per set of allowed
# hosts, then reused across many per-step agent invocations (each of which still gets
# its own fresh, ephemeral container — only the network + proxy are long-lived).
#
# Honesty note: written against documented `docker network`/`docker run` behaviour but
# not executed against a real Docker host in this project's own development
# environment (no Docker installed here). Validate before relying on it.
#
# Usage:
#   scripts/sandbox/provision_network.sh <network_name> <proxy_container_name> <host1> [host2 ...]
#
# Example:
#   scripts/sandbox/provision_network.sh gab-sandbox-net gab-egress-proxy api.anthropic.com

set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "usage: $0 <network_name> <proxy_container_name> <host1> [host2 ...]" >&2
    exit 1
fi

NETWORK_NAME="$1"
PROXY_CONTAINER="$2"
shift 2
ALLOWED_HOSTS=("$@")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_DIR="${SCRIPT_DIR}/egress_proxy"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "${BUILD_DIR}"' EXIT

# Render the Squid ACL from the declared allowlist — never left as a default-open
# wildcard, and always rebuilt fresh rather than edited in place, so a stale allowlist
# from a previous run can never silently linger.
HOSTS_LIST=$(IFS=' '; echo "${ALLOWED_HOSTS[*]}")
cp "${PROXY_DIR}/Dockerfile" "${BUILD_DIR}/Dockerfile"
sed "s/ALLOWED_HOSTS_PLACEHOLDER/${HOSTS_LIST}/" "${PROXY_DIR}/squid.conf.template" > "${BUILD_DIR}/squid.conf"

echo "Building egress proxy image (allowlist: ${HOSTS_LIST})..."
docker build -t gridactionbench-egress-proxy "${BUILD_DIR}"

# A dedicated bridge network with no external route except through the proxy
# container — sandboxed agent containers attach here, never to Docker's default
# bridge, so there is never an accidental path to the open internet.
if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    echo "Creating network ${NETWORK_NAME}..."
    docker network create --internal "${NETWORK_NAME}"
fi

# The proxy itself needs a second interface with real internet access (to actually
# reach the allowed model-provider hosts) — attached to the default bridge in addition
# to the internal sandbox network, so it can relay allowed CONNECT requests through.
if docker ps -a --format '{{.Names}}' | grep -qx "${PROXY_CONTAINER}"; then
    echo "Removing existing proxy container ${PROXY_CONTAINER}..."
    docker rm -f "${PROXY_CONTAINER}"
fi

echo "Starting egress proxy ${PROXY_CONTAINER} on network ${NETWORK_NAME}..."
docker run -d --name "${PROXY_CONTAINER}" --network "${NETWORK_NAME}" gridactionbench-egress-proxy
docker network connect bridge "${PROXY_CONTAINER}"

echo "Done. Pass network_name=${NETWORK_NAME}, egress_proxy_container=${PROXY_CONTAINER} to DockerSandboxBackend."
