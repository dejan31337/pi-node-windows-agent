
#!/usr/bin/env python3
"""
Pi Node Windows Agent 1.6
Compatible with Pi Network Node Monitor / SoloHost.

Python 3.10+
Windows 10/11 + Docker Desktop

GET:
  /health
  /status
  /peers
  /services
  /supervisor
  /logs?service=stellar-core&lines=500
  /logs?program=stellar-core&tail=500

POST:
  /service/stellar-core/start
  /service/stellar-core/stop
  /service/stellar-core/restart
  /services/start
  /services/stop
  /services/restart

Security:
  Bearer token authentication.
  Fixed Docker commands and service allowlist.
  No arbitrary Docker command execution.
"""

import os
import json
import hmac
import subprocess
import datetime
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

VERSION = "1.6"

HOST = os.environ.get("AGENT_HOST", "0.0.0.0")

PORT = int(os.environ.get("AGENT_PORT", "18765"))

CONTAINER = (
    os.environ.get("PI_NODE_CONTAINER")
    or os.environ.get("NODE_CONTAINER")
    or "testnet2"
).strip()

TOKEN = os.environ.get("NODE_STATUS_TOKEN", "").strip()

TIMEOUT = 30

MAX_LOG_LINES = 1000

ALLOWED_PROGRAMS = {
    "stellar-core",
    "postgresql",
    "horizon",
    "rpc",
}

ALLOWED_ACTIONS = {
    "start",
    "stop",
    "restart",
}


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def timestamp():
    return datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()


def docker_run(args, timeout=TIMEOUT):
    """
    Execute a fixed Docker CLI command.
    Never uses shell=True.
    """

    command = ["docker"] + args

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            ),
        )

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "Docker command timed out",
        }

    except FileNotFoundError:
        return {
            "ok": False,
            "error": (
                "Docker executable not found. "
                "Start Docker Desktop and check PATH."
            ),
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def docker_exec(args, timeout=TIMEOUT):
    return docker_run(
        ["exec", CONTAINER] + args,
        timeout,
    )


def error_message(result):
    return (
        result.get("stderr")
        or result.get("error")
        or "Docker command failed"
    )


def extract_json(output):
    """
    Extract the first valid JSON object from command output.
    """

    decoder = json.JSONDecoder()

    for index, char in enumerate(output):
        if char == "{":
            try:
                data, _ = decoder.raw_decode(
                    output[index:]
                )
                return data
            except json.JSONDecodeError:
                continue

    return None


# ---------------------------------------------------------
# NODE STATUS
# ---------------------------------------------------------

def get_status():
    result = docker_exec(
        ["node-status"]
    )

    if not result["ok"]:
        return {
            "ok": False,
            "error": error_message(result),
            "status": "",
            "container": CONTAINER,
            "timestamp": timestamp(),
        }

    report = result["stdout"]

    if result["stderr"]:
        report = (
            report + "\n" + result["stderr"]
        ).strip()

    if not report:
        return {
            "ok": False,
            "error": "node-status returned an empty report",
            "status": "",
            "container": CONTAINER,
            "timestamp": timestamp(),
        }

    # IMPORTANT:
    # The dashboard calls .strip() on the status value.
    # Therefore status MUST remain a plain string.

    return {
        "ok": True,
        "status": report,
        "container": CONTAINER,
        "timestamp": timestamp(),
    }


# ---------------------------------------------------------
# PEERS EXPLORER
# ---------------------------------------------------------

def get_peers():
    result = docker_exec([
        "stellar-core",
        "http-command",
        "peers",
    ])

    if not result["ok"]:
        return {
            "ok": False,
            "error": error_message(result),
            "output": "",
            "timestamp": timestamp(),
        }

    raw = result["stdout"]

    data = extract_json(raw)

    if data is not None:
        output = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
    else:
        output = raw

    if not output:
        return {
            "ok": False,
            "error": "Stellar Core returned empty peer information",
            "output": "",
            "timestamp": timestamp(),
        }

    return {
        "ok": True,
        "output": output,
        "peers": data,
        "timestamp": timestamp(),
    }


# ---------------------------------------------------------
# SUPERVISOR STATUS
# ---------------------------------------------------------

def get_supervisor_status():
    result = docker_exec([
        "supervisorctl",
        "status",
    ])

    if not result["ok"]:
        return {
            "ok": False,
            "error": error_message(result),
            "output": "",
            "status": "",
            "timestamp": timestamp(),
        }

    output = result["stdout"]

    return {
        "ok": True,
        "output": output,
        "status": output,
        "timestamp": timestamp(),
    }


# ---------------------------------------------------------
# SUPERVISOR LOG FILES
# ---------------------------------------------------------

def get_supervisor_logs(program, lines):
    """
    Read actual Supervisor stdout and stderr files.

    Example files:
      stellar-core-stdout---supervisor-*.log
      stellar-core-stderr---supervisor-*.log
    """

    if program not in ALLOWED_PROGRAMS:
        return {
            "ok": False,
            "error": "Unsupported Supervisor program",
            "output": "",
            "timestamp": timestamp(),
        }

    lines = max(
        1,
        min(int(lines), MAX_LOG_LINES),
    )

    # Program is restricted to ALLOWED_PROGRAMS.
    # Lines is converted to a bounded integer.
    #
    # Read both stdout and stderr, combine them,
    # then return the last requested number of lines.

    script = (
        "{ "
        "found=0; "

        f"for f in /var/log/supervisor/{program}-stdout---supervisor-*.log "
        f"/var/log/supervisor/{program}-stderr---supervisor-*.log; "
        "do "

        '[ -f "$f" ] || continue; '

        "found=1; "

        'printf "\\n===== %s =====\\n" "$f"; '

        'cat "$f"; '

        "done; "

        'if [ "$found" -eq 0 ]; then '
        'echo "No Supervisor log files found for this service."; '
        "fi; "

        f"}} | tail -n {lines}"
    )

    result = docker_exec([
        "sh",
        "-c",
        script,
    ])

    if not result["ok"]:
        return {
            "ok": False,
            "source": "supervisor",
            "program": program,
            "error": error_message(result),
            "output": "",
            "logs": "",
            "timestamp": timestamp(),
        }

    output = result["stdout"]

    if not output:
        output = "Supervisor log files exist but contain no output."

    message = (
        f"Loaded {program} logs · "
        f"{lines} lines requested"
    )

    return {
        "ok": True,
        "source": "supervisor",
        "program": program,
        "output": output,
        "logs": output,
        "message": message,
        "lines_requested": lines,
        "timestamp": timestamp(),
    }


# ---------------------------------------------------------
# DOCKER CONTAINER LOGS
# ---------------------------------------------------------

def get_docker_logs(lines):
    lines = max(
        1,
        min(int(lines), MAX_LOG_LINES),
    )

    result = docker_run([
        "logs",
        "--tail",
        str(lines),
        "--timestamps",
        CONTAINER,
    ])

    if not result["ok"]:
        return {
            "ok": False,
            "source": "docker",
            "error": error_message(result),
            "output": "",
            "timestamp": timestamp(),
        }

    output = result["stdout"]

    if result["stderr"]:
        if output:
            output += "\n"

        output += result["stderr"]

    return {
        "ok": True,
        "source": "docker",
        "output": output,
        "logs": output,
        "message": f"Loaded Docker logs · {lines} lines requested",
        "lines_requested": lines,
        "timestamp": timestamp(),
    }


# ---------------------------------------------------------
# LOG REQUEST COMPATIBILITY
# ---------------------------------------------------------

def handle_logs(params):
    """
    Supports both dashboard and newer parameter names:

      service=stellar-core&lines=500

      program=stellar-core&tail=500
    """

    program = (
        params.get("service", [None])[0]
        or params.get("program", [None])[0]
    )

    try:
        lines = int(
            params.get(
                "lines",
                params.get("tail", ["500"])
            )[0]
        )
    except (TypeError, ValueError):
        lines = 500

    lines = max(
        1,
        min(lines, MAX_LOG_LINES),
    )

    if program:
        return get_supervisor_logs(
            program,
            lines,
        )

    return get_docker_logs(lines)


# ---------------------------------------------------------
# SUPERVISOR SERVICE CONTROL
# ---------------------------------------------------------

def supervisor_action(program, action):
    if program not in ALLOWED_PROGRAMS:
        return {
            "ok": False,
            "error": "Unsupported service",
        }

    if action not in ALLOWED_ACTIONS:
        return {
            "ok": False,
            "error": "Unsupported service action",
        }

    result = docker_exec([
        "supervisorctl",
        action,
        program,
    ])

    if not result["ok"]:
        return {
            "ok": False,
            "error": error_message(result),
            "output": result.get("stdout", ""),
            "timestamp": timestamp(),
        }

    output = result["stdout"]

    return {
        "ok": True,
        "output": output or f"{action} {program} command completed",
        "program": program,
        "action": action,
        "timestamp": timestamp(),
    }


def supervisor_all_action(action):
    if action not in ALLOWED_ACTIONS:
        return {
            "ok": False,
            "error": "Unsupported service action",
        }

    result = docker_exec([
        "supervisorctl",
        action,
        "all",
    ])

    if not result["ok"]:
        return {
            "ok": False,
            "error": error_message(result),
            "output": result.get("stdout", ""),
            "timestamp": timestamp(),
        }

    return {
        "ok": True,
        "output": result["stdout"] or f"{action} all command completed",
        "action": action,
        "timestamp": timestamp(),
    }


# ---------------------------------------------------------
# HTTP HANDLER
# ---------------------------------------------------------

class AgentHandler(BaseHTTPRequestHandler):

    server_version = "PiNodeWindowsAgent/" + VERSION

    def send_json(self, data, code=200):
        body = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        self.send_response(code)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.end_headers()

        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self):
        if not TOKEN:
            return False

        authorization = self.headers.get(
            "Authorization",
            "",
        )

        supplied = ""

        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()

        if not supplied:
            supplied = self.headers.get(
                "X-Node-Status-Token",
                "",
            ).strip()

        return (
            bool(supplied)
            and hmac.compare_digest(
                supplied.encode("utf-8"),
                TOKEN.encode("utf-8"),
            )
        )

    def do_GET(self):
        parsed = urlparse(self.path)

        path = parsed.path.rstrip("/") or "/"

        params = parse_qs(parsed.query)

        # Public health endpoint.
        if path == "/health":
            return self.send_json({
                "ok": True,
                "service": "pi-node-windows-agent",
                "version": VERSION,
                "container": CONTAINER,
                "timestamp": timestamp(),
            })

        # Everything else requires authentication.
        if not self.authorized():
            return self.send_json({
                "ok": False,
                "error": "unauthorized",
            }, 401)

        if path == "/status":
            return self.send_json(
                get_status()
            )

        if path == "/peers":
            return self.send_json(
                get_peers()
            )

        if path == "/services":
            return self.send_json(
                get_supervisor_status()
            )

        if path == "/supervisor":
            return self.send_json(
                get_supervisor_status()
            )

        if path == "/logs":
            return self.send_json(
                handle_logs(params)
            )

        return self.send_json({
            "ok": False,
            "error": "not_found",
            "available_endpoints": [
                "/health",
                "/status",
                "/peers",
                "/services",
                "/supervisor",
                "/logs",
            ],
        }, 404)

    def do_POST(self):
        if not self.authorized():
            return self.send_json({
                "ok": False,
                "error": "unauthorized",
            }, 401)

        parsed = urlparse(self.path)

        path = parsed.path.strip("/")

        parts = path.split("/")

        # Individual service:
        # POST /service/stellar-core/restart

        if (
            len(parts) == 3
            and parts[0] == "service"
        ):
            program = parts[1]
            action = parts[2]

            return self.send_json(
                supervisor_action(
                    program,
                    action,
                )
            )

        # All services:
        # POST /services/restart

        if (
            len(parts) == 2
            and parts[0] == "services"
        ):
            action = parts[1]

            return self.send_json(
                supervisor_all_action(action)
            )

        return self.send_json({
            "ok": False,
            "error": "not_found",
        }, 404)

    def log_message(self, fmt, *args):
        print(
            "[{}] {}".format(
                timestamp(),
                fmt % args,
            ),
            flush=True,
        )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():
    if not TOKEN:
        raise SystemExit(
            "ERROR: NODE_STATUS_TOKEN is missing. "
            "Load your .env file before starting the agent."
        )

    server = ThreadingHTTPServer(
        (HOST, PORT),
        AgentHandler,
    )

    server.daemon_threads = True

    print("=" * 58, flush=True)
    print("Pi Node Windows Agent " + VERSION, flush=True)
    print("Container: " + CONTAINER, flush=True)
    print("Listening: {}:{}".format(HOST, PORT), flush=True)
    print("Authentication: enabled", flush=True)
    print("Supervisor log files: enabled", flush=True)
    print("Service controls: enabled", flush=True)
    print("Peers Explorer: enabled", flush=True)
    print("Read-only monitoring endpoints: enabled", flush=True)
    print("=" * 58, flush=True)

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("Stopping agent...", flush=True)

    finally:
        server.server_close()


if __name__ == "__main__":
    main()
