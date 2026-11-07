"""Canonical, default-deny Squid policy shared by provisioning and verification."""

from gridactionbench.agents.sandboxed import validate_hosts


def render_proxy_config(hosts: tuple[str, ...]) -> str:
    hosts = validate_hosts(hosts)
    if not hosts:
        raise ValueError("a networked proxy requires at least one allowed hostname")
    return "\n".join([
        "http_port 3128",
        "acl allowed_hosts dstdomain " + " ".join(hosts),
        "acl SSL_ports port 443",
        "acl CONNECT method CONNECT",
        "acl private_dst dst 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 "
        "169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4 "
        "::/128 ::1/128 ::ffff:0:0/96 fc00::/7 fe80::/10 ff00::/8",
        "http_access deny !SSL_ports",
        "http_access deny private_dst",
        "http_access allow CONNECT allowed_hosts",
        "http_access deny all",
        "access_log stdio:/dev/stdout squid",
        "buffered_logs off",
        "cache_log /dev/stderr",
        "cache_store_log none",
        "pid_filename /tmp/squid.pid",
        "coredump_dir /tmp",
        "cache deny all",
        "shutdown_lifetime 0 seconds",
        "",
    ])


def normalized_policy(text: str) -> list[str]:
    return [" ".join(line.split()) for raw in text.splitlines()
            if (line := raw.split("#", 1)[0].strip())]


if __name__ == "__main__":
    import sys
    print(render_proxy_config(tuple(sys.argv[1:])), end="")
