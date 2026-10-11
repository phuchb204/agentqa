from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


def _write_reports(report_dir: Path, result: dict) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{result['profile']}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    profiles: dict[str, dict] = {}
    for path in sorted(report_dir.glob("*.json")):
        if path.name == "latest.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        profiles[data.get("profile", path.stem)] = {
            "ok": data.get("ok") is True,
            "report": path.name,
        }
    expected = {"windows", "linux"}
    latest = {
        "schema_version": "os-smoke-report/1",
        "tool": "run_os_profile_smoke",
        "ok": expected <= set(profiles) and all(profiles[name]["ok"] for name in expected),
        "profiles": profiles,
        "generated_at": _now_iso(),
    }
    (report_dir / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return latest


def _check(name: str, ok: bool, detail: str, *, blocked_reason: str | None = None) -> dict:
    payload: dict = {"name": name, "ok": ok, "detail": detail}
    if blocked_reason:
        payload["blocked_reason"] = blocked_reason
    return payload


def run_windows_profile(repo_root: Path) -> dict:
    checks: list[dict] = []

    version_ok = sys.version_info[:2] == (3, 13)
    pin_file = repo_root / ".python-version"
    pin_ok = pin_file.is_file() and pin_file.read_text(encoding="utf-8").strip() == "3.13"
    imports: list[str] = []
    import_error = ""
    for module in ("agentqa.contracts", "agentqa.models", "agentqa.agent", "agentqa.verify", "agentqa.platform"):
        try:
            __import__(module)
            imports.append(module)
        except Exception as error:
            import_error = f"{module}: {error}"
            break
    core_ok = version_ok and pin_ok and not import_error
    runtime_detail = (
        f"python={sys.version_info.major}.{sys.version_info.minor} pin={pin_ok} imports={len(imports)}/5 {import_error}"
    ).strip()
    checks.append(_check("core.runtime", core_ok, runtime_detail))

    cli_command = [
        sys.executable,
        "-c",
        "from agentqa.platform.cli import main; main(['--help'])",
    ]
    cli_completed = subprocess.run(
        cli_command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    cli_ok = cli_completed.returncode == 0 and "usage" in (cli_completed.stdout + cli_completed.stderr).lower()
    checks.append(_check("cli.help", cli_ok, f"exit={cli_completed.returncode}"))

    lock_ok = (repo_root / "uv.lock").is_file() and (repo_root / "pnpm-lock.yaml").is_file() and pin_ok
    checks.append(_check("lockfile.runtime", lock_ok, "uv.lock + pnpm-lock.yaml + .python-version=3.13"))

    browser_ok = False
    browser_detail = ""
    egress_ok = False
    egress_detail = ""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        from agentqa.platform.security.sandbox import select_profile

        temp_root = Path(tempfile.mkdtemp(prefix="agentqa-os-smoke-"))
        dead_proxy = "http://127.0.0.1:9"
        profile = select_profile(workspace_root=str(repo_root), temp_root=str(temp_root), proxy_url=dead_proxy)
        profile.enforce()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=list(profile.launch.args),
                env=profile.launch.clean_environment(),
            )
            try:
                page = browser.new_page()
                page.goto("about:blank")
                page.set_content("<title>os-smoke</title><p>ok</p>")
                browser_ok = page.title() == "os-smoke"
                browser_detail = f"chromium {browser.version}"
            finally:
                browser.close()
            browser = playwright.chromium.launch(
                headless=True,
                args=list(profile.launch.args),
                proxy={"server": dead_proxy},
                env=profile.launch.clean_environment(),
            )
            try:
                page = browser.new_page()
                page.goto("http://example.com", timeout=8000)
                egress_detail = "goto qua proxy đóng thành công (không chặn)"
            except PlaywrightError as error:
                egress_ok = "ERR_PROXY" in str(error) or "ERR_TUNNEL" in str(error) or "PROXY" in str(error)
                egress_detail = f"chặn qua proxy: {str(error)[:120]}"
            finally:
                browser.close()
    except ImportError as error:
        browser_detail = f"playwright thiếu: {error}"
        egress_detail = browser_detail
    except Exception as error:
        browser_detail = f"{type(error).__name__}: {error}"
        egress_detail = browser_detail

    checks.append(
        _check(
            "browser.launch",
            browser_ok,
            browser_detail,
            blocked_reason=None if browser_ok else "browser_blocked",
        )
    )

    config_enforced = False
    config_detail = ""
    try:
        from agentqa.agent.browser.contexts import BrowserLaunchConfig, SandboxUnsupported
        from agentqa.platform.security.sandbox_windows import windows_profile

        try:
            windows_profile(workspace_root=str(repo_root), temp_root=str(repo_root), proxy_url="")
            config_detail = "profile không enforce khi thiếu proxy"
        except SandboxUnsupported:
            config_enforced = True
            config_detail = "enforce từ chối proxy_url rỗng và temp ngoài temp root"
        assert BrowserLaunchConfig().env_scrub
    except Exception as error:
        config_detail = f"{type(error).__name__}: {error}"
    checks.append(_check("egress.config_enforced", config_enforced, config_detail))
    checks.append(_check("egress.proxy_required", egress_ok, egress_detail))

    return {
        "profile": "windows",
        "ok": all(item["ok"] for item in checks),
        "checks": checks,
        "generated_at": _now_iso(),
    }


def run_linux_profile(*, image: str, proxy_port: int) -> dict:
    if not _docker_available():
        return {
            "profile": "linux",
            "ok": False,
            "blocked_reason": "docker_unavailable",
            "checks": [],
            "generated_at": _now_iso(),
        }
    suffix = secrets.token_hex(4)
    internal_network = f"agentqa-smoke-internal-{suffix}"
    proxy_name = f"agentqa-smoke-proxy-{suffix}"
    checks: list[dict] = []
    try:
        _docker("network", "create", "--internal", internal_network)
        checks.append(_check("network.internal_created", True, internal_network))
        _docker(
            "run",
            "-d",
            "--name",
            proxy_name,
            "--network",
            "bridge",
            image,
            "python",
            "-c",
            PROXY_SCRIPT,
            str(proxy_port),
        )
        _docker("network", "connect", internal_network, proxy_name)
        inspect = _docker(
            "inspect",
            proxy_name,
            "--format",
            '{{(index .NetworkSettings.Networks "' + internal_network + '").IPAddress}}',
        )
        proxy_ip = inspect.stdout.strip()
        checks.append(_check("proxy.ready", bool(proxy_ip), f"internal_ip={proxy_ip}"))
        run = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                internal_network,
                image,
                "python",
                "-c",
                APP_SCRIPT,
                proxy_ip,
                str(proxy_port),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=180,
        )
        output = (run.stdout or "") + (run.stderr or "")
        if "DIRECT_CONNECT_OK" in output:
            checks.append(_check("egress.direct_blocked", False, "direct egress không bị chặn"))
        else:
            checks.append(_check("egress.direct_blocked", True, "DIRECT_CONNECT_BLOCKED"))
        proxy_ok = run.returncode == 0 and "PROXY_STATUS 200" in output
        checks.append(
            _check(
                "egress.proxy_reachable",
                proxy_ok,
                output.strip().splitlines()[-1] if output.strip() else f"exit={run.returncode}",
            )
        )
    except subprocess.TimeoutExpired:
        checks.append(_check("egress.timeout", False, "timeout 180s"))
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        checks.append(_check("docker.operation", False, f"{type(error).__name__}"))
    finally:
        _docker("rm", "-f", proxy_name, check=False)
        _docker("network", "rm", internal_network, check=False)
    return {
        "profile": "linux",
        "ok": bool(checks) and all(item["ok"] for item in checks),
        "checks": checks,
        "image": image,
        "generated_at": _now_iso(),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="run_os_profile_smoke", description="Smoke core/CLI/browser/egress cho OS profile Windows và Linux."
    )
    parser.add_argument("--profile", choices=["windows", "linux", "all"], default="all")
    parser.add_argument("--image", default="python:3.13-slim")
    parser.add_argument("--proxy-port", type=int, default=8899)
    parser.add_argument("--report-dir", default="artifacts/os-smoke")
    args = parser.parse_args(argv)

    report_dir = REPO_ROOT / args.report_dir
    results: list[dict] = []
    if args.profile in ("windows", "all"):
        results.append(run_windows_profile(REPO_ROOT))
    if args.profile in ("linux", "all"):
        results.append(run_linux_profile(image=args.image, proxy_port=args.proxy_port))
    for result in results:
        _write_reports(report_dir, result)
    latest = _write_reports(report_dir, results[-1])
    summary = {
        "ok": all(result["ok"] for result in results),
        "latest": latest,
        "profiles": [
            {"profile": result["profile"], "ok": result["ok"], "checks": result["checks"]} for result in results
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
