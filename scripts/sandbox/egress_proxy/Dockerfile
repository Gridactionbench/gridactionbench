# Minimal allowlisting egress proxy image for the GridActionBench agent sandbox.
# See docs/architecture/adr/ADR-019-agent-execution-sandbox.md.
#
# Honesty note: this Dockerfile and the canonical proxy policy are experimental,
# against Squid's documented configuration syntax, but have not been built or run
# against a real Docker host in this project's own development environment (no Docker
# installed here). Validate before relying on it for a real Verified-tier run.

FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends squid \
    && rm -rf /var/lib/apt/lists/*

COPY squid.conf /etc/squid/squid.conf

EXPOSE 3128

USER 65532:65532

ENTRYPOINT ["squid", "-N", "-f", "/etc/squid/squid.conf"]
