from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys

PROXY_SCRIPT = r"""
import http.client
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.scheme != "http" or not parts.hostname:
            self.send_error(400, "absolute-form required")
            return
        try:
            upstream = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=10)
            upstream.request("GET", parts.path or "/", headers={"Host": parts.hostname})
            response = upstream.getresponse()
            body = response.read()
        except OSError:
            self.send_error(502, "upstream unavailable")
            return
        self.send_response(response.status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


server = ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Handler)
print("READY", flush=True)
server.serve_forever()
"""

APP_SCRIPT = r"""
import http.client
import socket
import sys
import time

proxy_host = sys.argv[1]
proxy_port = int(sys.argv[2])

try:
    connection = socket.create_connection(("1.1.1.1", 80), timeout=4)
    connection.close()
    print("DIRECT_CONNECT_OK")
    sys.exit(3)
except OSError:
    print("DIRECT_CONNECT_BLOCKED")

last_error = None
for _ in range(15):
    try:
        client = http.client.HTTPConnection(proxy_host, proxy_port, timeout=10)
        client.request("GET", "http://example.com/", headers={"Host": "example.com"})
        response = client.getresponse()
        response.read()
        print("PROXY_STATUS", response.status)
        sys.exit(0 if response.status < 500 else 4)
    except OSError as error:
        last_error = error
        time.sleep(1)
print("PROXY_UNREACHABLE", last_error)
sys.exit(4)
"""


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _docker_available() -> bool:
    try:
        _docker("version", "--format", "{{.Server.Version}}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke enforcement egress cho OS profile linux trong container.")
    parser.add_argument("--profile", choices=["linux"], default="linux")
    parser.add_argument("--image", default="python:3.13-slim")
    parser.add_argument("--proxy-port", type=int, default=8899)
    args = parser.parse_args(argv)

    if not _docker_available():
        print(json.dumps({"ok": False, "reason": "docker_unavailable"}, ensure_ascii=False))
        return 2

    suffix = secrets.token_hex(4)
    internal_network = f"agentqa-smoke-internal-{suffix}"
    proxy_name = f"agentqa-smoke-proxy-{suffix}"
    steps: list[dict] = []
    try:
        _docker("network", "create", "--internal", internal_network)
        steps.append({"step": "network_created", "name": internal_network})

        _docker(
            "run",
            "-d",
            "--name",
            proxy_name,
            "--network",
            "bridge",
            args.image,
            "python",
            "-c",
            PROXY_SCRIPT,
            str(args.proxy_port),
        )
        _docker("network", "connect", internal_network, proxy_name)
        inspect = _docker(
            "inspect",
            proxy_name,
            "--format",
            '{{(index .NetworkSettings.Networks "' + internal_network + '").IPAddress}}',
        )
        proxy_ip = inspect.stdout.strip()
        steps.append({"step": "proxy_ready", "internal_ip": proxy_ip})

        run = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                internal_network,
                args.image,
                "python",
                "-c",
                APP_SCRIPT,
                proxy_ip,
                str(args.proxy_port),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=180,
        )
        output = (run.stdout or "") + (run.stderr or "")
        steps.append({"step": "app_check", "exit": run.returncode, "output": output.strip().splitlines()})
        if "DIRECT_CONNECT_OK" in output:
            print(json.dumps({"ok": False, "reason": "direct_egress_not_blocked", "steps": steps}, ensure_ascii=False))
            return 2
        if run.returncode != 0 or "PROXY_STATUS 200" not in output:
            print(json.dumps({"ok": False, "reason": "proxy_egress_failed", "steps": steps}, ensure_ascii=False))
            return 2
        print(
            json.dumps(
                {
                    "ok": True,
                    "profile": args.profile,
                    "direct_egress": "blocked",
                    "proxy_egress": "reachable",
                    "steps": steps,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "reason": "timeout", "steps": steps}, ensure_ascii=False))
        return 2
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        print(json.dumps({"ok": False, "reason": f"{type(error).__name__}", "steps": steps}, ensure_ascii=False))
        return 2
    finally:
        _docker("rm", "-f", proxy_name, check=False)
        _docker("network", "rm", internal_network, check=False)


if __name__ == "__main__":
    sys.exit(main())
