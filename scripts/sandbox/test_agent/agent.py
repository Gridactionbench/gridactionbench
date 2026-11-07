"""Deliberately hostile modes for opt-in Docker tests; never a benchmark submission."""
import json
import os
import socket
import sys
import time
from urllib.parse import urlparse

mode = os.environ.get("GAB_TEST_MODE", "idle")
sys.stdin.read()
if mode == "timeout":
    time.sleep(120)
elif mode == "flood":
    while True:
        sys.stdout.write("x" * 8192)
        sys.stdout.flush()
elif mode == "network":
    direct_blocked = False
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=1).close()
    except OSError:
        direct_blocked = True
    proxy = urlparse(os.environ["HTTPS_PROXY"])
    with socket.create_connection((proxy.hostname, proxy.port), timeout=5) as stream:
        stream.sendall(b"CONNECT example.com:444 HTTP/1.1\r\nHost: example.com:444\r\n\r\n")
        denied = b"403" in stream.recv(4096).split(b"\r\n", 1)[0]
    print(json.dumps({"direct_blocked": direct_blocked, "proxy_denied": denied}))
else:
    print('{"action":"IDLE"}')
