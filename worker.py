#!/usr/bin/env python3
"""
HTTP Worker Agent for BobTheBot cluster.
Runs on Pi Zero Ws. Accepts tasks via HTTP, calls Gemini, runs tools, returns results.

Usage: python3 worker.py [port]
Default port: 5000
"""

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(DIR, "config.json")) as f:
    CFG = json.load(f)

GEMINI_PROXY = CFG.get("gemini_proxy", "http://172.19.181.254:8787")
HOSTNAME = os.uname().nodename

SYSTEM_PROMPT = """You are a worker agent in a home assistant cluster.
You receive tasks and execute them using available tools.
Be concise and return only the result, not your reasoning process.

Available tools (run via exec):
- python3 calendar-tool.py list [--days N]
- python3 calendar-tool.py search "query"
- python3 email-tool.py inbox / unread / search "query" / read <id>
- python3 weather-tool.py [--forecast | --hourly]
- python3 traffic-tool.py "destination" ["origin"]
- python3 traffic-tool.py lookup "place name"

When a task mentions running a tool, execute it and return the output.
When a task requires research, use your knowledge to provide a thorough answer.
"""


def run_tool(cmd, timeout=30):
    """Run a tool command and return output."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout, cwd=DIR)
        return r.stdout.strip() if r.returncode == 0 else f"Error: {r.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: timeout"
    except Exception as e:
        return f"Error: {e}"


def call_gemini(task):
    """Call Gemini via proxy and return response."""
    body = json.dumps({
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task}
        ],
        "max_tokens": 2048,
        "temperature": 0.3
    }).encode()

    req = urllib.request.Request(
        f"{GEMINI_PROXY}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error calling Gemini: {e}"


def process_task(task):
    """Process a task: if it mentions a tool command, run it. Otherwise ask Gemini."""
    # Check if task contains a direct tool command
    tool_prefixes = [
        "python3 calendar-tool", "python3 email-tool",
        "python3 weather-tool", "python3 traffic-tool"
    ]
    for prefix in tool_prefixes:
        if prefix in task:
            # Extract the command
            start = task.index(prefix)
            # Find end of command (next newline or end of string)
            end = task.find("\n", start)
            cmd = task[start:end] if end != -1 else task[start:]
            result = run_tool(cmd.strip())
            # If task has more context, send tool output to Gemini for formatting
            if len(task) > len(cmd) + 10:
                return call_gemini(f"Task: {task}\n\nTool output:\n{result}\n\nFormat this into a clear answer.")
            return result

    # No direct tool command, use Gemini
    return call_gemini(task)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/task":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            task = body.get("task", "")

            if not task:
                self.send_json(400, {"error": "missing 'task' field"})
                return

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Task: {task[:80]}...")
            result = process_task(task)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Done: {result[:80]}...")

            self.send_json(200, {
                "result": result,
                "worker": HOSTNAME,
                "timestamp": datetime.now().isoformat()
            })
        else:
            self.send_json(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {
                "status": "ok",
                "worker": HOSTNAME,
                "timestamp": datetime.now().isoformat()
            })
        else:
            self.send_json(404, {"error": "not found"})

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # suppress default logging


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Worker {HOSTNAME} listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
