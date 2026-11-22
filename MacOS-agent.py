
#!/usr/bin/env python3
"""
Pi Node Monitor - macOS Helper
Version: 1.0

Compatible with Pi Node Monitor dashboard / Windows Agent 1.6 API.
Uses Docker Desktop to communicate with the Pi Node container.
"""

import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

VERSION = "1.0"

HOST = os.getenv("AGENT_HOST", "0.0.0.0")
PORT = int(os.getenv("AGENT_PORT", "18765"))
TOKEN = os.getenv("NODE_STATUS_TOKEN", "")
CONTAINER = os.getenv(
    "PI_NODE_CONTAINER",
    os.getenv("NODE_CONTAINER", "testnet2")
)

ALLOWED_PROGRAMS = {
    "stellar-core",
    "postgresql",
    "horizon",
    "rpc",
}

ALLOWED_ACTIONS = {"start", "stop", "restart"}
MAX_LINES = 1000
TIMEOUT = 30


def load_env_file():
    """Load .env values without requiring third-party packages."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    if not os.path.isfile(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()

HOST = os.getenv("AGENT_HOST", "0.0.0.0")
PORT = int(os.getenv("AGENT_PORT", "18765"))
TOKEN = os.getenv("NODE_STATUS_TOKEN", "")
CONTAINER = os.getenv(
    "PI_NODE_CONTAINER",
    os.getenv("NODE_CONTAINER", "testnet2")
)


def run_command(command, timeout=TIMEOUT):
    """Run a fixed local command and return its result."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "output": output,
            "error": error
        }

    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "output": "",
            "error": "Command timed out"
        }

    except FileNotFoundError:
        return {
            "ok": False,
            "returncode": -1,
            "output": "",
            "error": "Docker command not found. Install and start Docker Desktop."
        }

    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "output": "",
            "error": str(exc)
        }


def docker_exec(*args, timeout=TIMEOUT):
    return run_command(
        ["docker", "exec", CONTAINER, *args],
        timeout=timeout
    )


def parse_json_output(output):
    try:
        return json.loads(output)
    except (ValueError, TypeError):
        return None


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "PiNodeMacOSAgent/" + VERSION

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Node-Status-Token"
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_json({"ok": True})

    def authorized(self):
        auth = self.headers.get("Authorization", "")
        supplied = ""

        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()

        if not supplied:
            supplied = self.headers.get("X-Node-Status-Token", "").strip()

        return bool(TOKEN) and supplied == TOKEN

    def require_auth(self):
        if not self.authorized():
            self.send_json(
                {"ok": False, "error": "Unauthorized"},
                401
            )
            return False

        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        # Public health endpoint
        if path == "/health":
            self.send_json({
                "ok": True,
                "service": "pi-node-macos-agent",
                "version": VERSION
            })
            return

        if not self.require_auth():
            return

        if path == "/status":
            self.get_status()
        elif path == "/peers":
            self.get_peers()
        elif path in ("/services", "/supervisor"):
            self.get_services()
        elif path == "/logs":
            self.get_logs(params)
        else:
            self.send_json(
                {"ok": False, "error": "Endpoint not found"},
                404
            )

    def get_status(self):
        result = docker_exec("node-status")

        if not result["ok"]:
            self.send_json({
                "ok": False,
                "error": result["error"] or result["output"],
                "status": "Unavailable"
            }, 502)
            return

        data = parse_json_output(result["output"])

        if isinstance(data, dict):
            # Dashboard expects status to be a plain string.
            if not isinstance(data.get("status"), str):
                data["status"] = str(data.get("status", "Unknown"))

            data["ok"] = data.get("ok", True)
            self.send_json(data)
        else:
            self.send_json({
                "ok": True,
                "status": result["output"] or "Unknown",
                "output": result["output"]
            })

    def get_peers(self):
        result = docker_exec(
            "stellar-core",
            "http-command",
            "peers"
        )

        if not result["ok"]:
            self.send_json({
                "ok": False,
                "error": result["error"] or result["output"],
                "output": result["output"],
                "peers": []
            }, 502)
            return

        parsed = parse_json_output(result["output"])

        self.send_json({
            "ok": True,
            "output": result["output"],
            "peers": parsed if parsed is not None else result["output"]
        })

    def get_services(self):
        result = docker_exec("supervisorctl", "status")

        self.send_json({
            "ok": result["ok"],
            "status": result["output"],
            "output": result["output"],
            "error": result["error"]
        }, 200 if result["ok"] else 502)

    def get_logs(self, params):
        program = (
            params.get("service", [None])[0]
            or params.get("program", ["stellar-core"])[0]
        )

        raw_lines = (
            params.get("lines", [None])[0]
            or params.get("tail", ["200"])[0]
        )

        if program not in ALLOWED_PROGRAMS:
            self.send_json({
                "ok": False,
                "error": "Unsupported service name"
            }, 400)
            return

        try:
            lines = max(1, min(int(raw_lines), MAX_LINES))
        except (ValueError, TypeError):
            lines = 200

        # Program name is checked against a fixed allowlist above.
        script = (
            'for f in '
            f'/var/log/supervisor/{program}-stdout---supervisor-*.log '
            f'/var/log/supervisor/{program}-stderr---supervisor-*.log; '
            'do '
            '[ -f "$f" ] || continue; '
            'echo "===== $f ====="; '
            'cat "$f"; '
            'done'
        )

        result = docker_exec("sh", "-c", script)

        output = result["output"]

        if output:
            output = "\n".join(output.splitlines()[-lines:])

        self.send_json({
            "ok": result["ok"],
            "service": program,
            "output": output,
            "logs": output,
            "error": result["error"]
        }, 200 if result["ok"] else 502)

    def do_POST(self):
        if not self.require_auth():
            return

        path = urlparse(self.path).path.rstrip("/")
        parts = [part for part in path.split("/") if part]

        if len(parts) == 3 and parts[0] == "service":
            program, action = parts[1], parts[2]

            if program not in ALLOWED_PROGRAMS:
                self.send_json({
                    "ok": False,
                    "error": "Unsupported service name"
                }, 400)
                return

            if action not in ALLOWED_ACTIONS:
                self.send_json({
                    "ok": False,
                    "error": "Unsupported action"
                }, 400)
                return

            self.run_service_action(action, program)
            return

        if len(parts) == 2 and parts[0] == "services":
            action = parts[1]

            if action not in ALLOWED_ACTIONS:
                self.send_json({
                    "ok": False,
                    "error": "Unsupported action"
                }, 400)
                return

            self.run_service_action(action, "all")
            return

        self.send_json({
            "ok": False,
            "error": "Endpoint not found"
        }, 404)

    def run_service_action(self, action, program):
        result = docker_exec(
            "supervisorctl",
            action,
            program
        )

        self.send_json({
            "ok": result["ok"],
            "action": action,
            "service": program,
            "output": result["output"],
            "error": result["error"]
        }, 200 if result["ok"] else 502)

    def log_message(self, fmt, *args):
        print("[PiNodeMacOSAgent] " + (fmt % args))


def main():
    if not TOKEN:
        print("ERROR: NODE_STATUS_TOKEN is missing.")
        print("Create a .env file and configure your private token.")
        raise SystemExit(1)

    print("========================================")
    print(" Pi Node Monitor - macOS Helper")
    print(" Version:", VERSION)
    print(" Container:", CONTAINER)
    print(" Listening:", f"{HOST}:{PORT}")
    print("========================================")

    docker_check = run_command(["docker", "version", "--format", "{{.Server.Version}}"])

    if not docker_check["ok"]:
        print("WARNING: Docker is not available.")
        print(docker_check["error"] or docker_check["output"])
        print("Start Docker Desktop and check the container name.")

    server = ThreadingHTTPServer((HOST, PORT), AgentHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping macOS Helper...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
