#!/usr/bin/env python3
"""Read-only bridge for Pi Node Monitor Pro. Python 3.10+, Docker Desktop."""
import hmac
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("AGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("AGENT_PORT", "18765"))
CONTAINER = os.environ.get("PI_NODE_CONTAINER", "testnet2")
TOKEN = os.environ.get("NODE_STATUS_TOKEN", "").strip()

def get_node_report():
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER, "node-status"],
            capture_output=True, text=True, timeout=25, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except FileNotFoundError:
        return None, "Docker CLI not found. Start Docker Desktop and ensure docker.exe is on PATH."
    except subprocess.TimeoutExpired:
        return None, "docker exec node-status timed out after 25 seconds."

    report = (result.stdout or "").strip()
    if result.stderr:
        report = (report + "\n" + result.stderr.strip()).strip()

    if result.returncode != 0:
        return None, report or f"docker exec exited with code {result.returncode}"
    if not report:
        return None, "node-status returned an empty report."
    return report, None

class Handler(BaseHTTPRequestHandler):
    server_version = "PiNodeWindowsAgent/1.1"

    def send_json(self, code, obj):
        import json
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"ok": True, "service": "pi-node-windows-agent"})
        if self.path != "/status":
            return self.send_json(404, {"ok": False, "error": "not_found"})
        if not TOKEN:
            return self.send_json(503, {"ok": False, "error": "NODE_STATUS_TOKEN is not configured"})
        auth = self.headers.get("Authorization", "")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied.encode(), TOKEN.encode()):
            return self.send_json(401, {"ok": False, "error": "unauthorized"})

        report, error = get_node_report()
        if error:
            return self.send_json(503, {
                "ok": False, "error": error, "container": CONTAINER
            })

        # IMPORTANT: app.py calls raw.strip(), so "status" MUST be a string.
        return self.send_json(200, {
            "ok": True,
            "status": report,
            "container": CONTAINER
        })

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

def main():
    if not TOKEN:
        raise SystemExit("NODE_STATUS_TOKEN is missing. Run install.bat and configure the token.")
    print(f"Pi Node Windows Agent 1.1 listening on {HOST}:{PORT}")
    print(f"Container: {CONTAINER}; endpoint: http://host.docker.internal:{PORT}/status")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
