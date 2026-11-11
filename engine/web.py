"""Optional local web UI: standard-library http.server bound to 127.0.0.1.

GET  /             the single page (web/index.html)
GET  /api/schema   the input schema (field path, kind, required, default, allowed values)
GET  /api/samples  public scenarios and edge cases shipped in scenarios/
POST /api/evaluate scenario JSON (object or array) -> list of output documents (same parse_text as the CLI)

The page only calls this server; nothing is fetched from the internet and no LLM is involved.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .load import parse_text
from .validate import EXTRA_PATHS, FIELDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BODY = 2_000_000


def schema():
    return [{"path": p, "kind": k, "required": r, "default": d, "choices": e if isinstance(e, list) else None, "extra": p in EXTRA_PATHS}
            for p, k, r, d, e in FIELDS]


def samples():
    out = []
    with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
        for s in json.load(f):
            out.append({"id": s["scenario_id"], "label": f"{s['scenario_id']} {s['project']['name']}", "scenario": s})
    for sub in ("edge_cases", "extras", "hidden_like"):
        edir = os.path.join(ROOT, "scenarios", sub)
        for name in sorted(os.listdir(edir)) if os.path.isdir(edir) else []:
            if name.endswith(".json"):
                with open(os.path.join(edir, name), encoding="utf-8") as f:
                    text = f.read()
                try:
                    data = json.loads(text)
                except ValueError:
                    data = text  # malformed on purpose (an edge case); sent as raw text
                out.append({"id": name[:-5], "label": name[:-5].replace("_", " "), "scenario": data})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "StackSense"

    def log_message(self, fmt, *args):  # keep the terminal quiet; errors still surface as HTTP codes
        pass

    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False, indent=2), "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(ROOT, "web", "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/api/schema":
            self._json(200, schema())
        elif self.path == "/api/samples":
            self._json(200, samples())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/evaluate":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0  # malformed header: same 400 as a missing body
        if n <= 0 or n > MAX_BODY:
            return self._json(413 if n > MAX_BODY else 400, {"error": "body must be 1 byte to 2 MB of JSON"})
        try:
            text = self.rfile.read(n).decode("utf-8")
        except UnicodeDecodeError:
            return self._json(400, {"error": "body must be UTF-8"})
        self._json(200, parse_text(text))


def make_server(port=8765, host="127.0.0.1"):
    return ThreadingHTTPServer((host, port), Handler)


def serve(port=8765):
    srv = make_server(port)
    print(f"StackSense UI on http://127.0.0.1:{srv.server_address[1]}/  (Ctrl+C to stop; local only, no LLM, no internet)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
