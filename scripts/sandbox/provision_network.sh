#!/usr/bin/env bash
# Provision a trusted proxy blueprint. Agent runs clone it into isolated resources.
set -euo pipefail
if [ "$#" -lt 3 ]; then
    echo "usage: $0 <network_name> <proxy_container_name> <host1> [host2 ...]" >&2
    exit 1
fi
NETWORK_NAME="$1"
PROXY_CONTAINER="$2"
shift 2
for RESOURCE_NAME in "${NETWORK_NAME}" "${PROXY_CONTAINER}"; do
    if [[ ! "${RESOURCE_NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
        echo "Invalid Docker resource name" >&2
        exit 1
    fi
done
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "${BUILD_DIR}"' EXIT
# Python validates exact hostnames and renders the same policy the backend verifies.
python -m gridactionbench.agents.proxy_policy "$@" > "${BUILD_DIR}/squid.conf"
cp "${SCRIPT_DIR}/egress_proxy/Dockerfile" "${BUILD_DIR}/Dockerfile"
# Never replace or silently reuse somebody else's infrastructure.
if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    echo "Network already exists; choose a fresh blueprint name" >&2
    exit 1
fi
if docker container inspect "${PROXY_CONTAINER}" >/dev/null 2>&1; then
    echo "Proxy container already exists; choose a fresh blueprint name" >&2
    exit 1
fi
docker build -t gridactionbench-egress-proxy "${BUILD_DIR}"
docker network create --driver bridge --internal "${NETWORK_NAME}"
docker run -d --name "${PROXY_CONTAINER}" --network bridge \
    --read-only --tmpfs /tmp:rw,size=16m --memory 128m --cpus 0.5 \
    --pids-limit 64 --cap-drop ALL --security-opt no-new-privileges \
    --log-driver local --log-opt max-size=1m --log-opt max-file=1 \
    gridactionbench-egress-proxy
docker network connect "${NETWORK_NAME}" "${PROXY_CONTAINER}"
echo "Blueprint created. Verify Squid startup before using it."
