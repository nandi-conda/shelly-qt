"""A tiny stand-in for the prefix-alpm server's HTTP API (search/add/status)."""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CATALOG = {  # (channel, name): (version, summary)
    ("conda-forge", "httpie"): ("3.2.4", "a CLI, cURL-like tool for humans"),
    ("conda-forge", "httpx"): ("0.28.1", "The next generation HTTP client."),
    ("conda-forge", "ripgrep"): ("15.2.0", "ripgrep recursively searches directories for a regex pattern"),
    ("conda-forge", "pixi"): ("0.84.0", "pixi package manager"),
    ("github-releases", "pixi"): ("0.83.0", "pixi from GitHub releases"),
}


class State:
    added: dict = {"ripgrep": "conda-forge"}  # name -> channel the repo serves it from
    calls: list = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        qs = urllib.parse.parse_qs(url.query)
        State.calls.append((url.path, qs))
        if url.path == "/status":
            return self._send({"mode": "dynamic", "packages": len(State.added)})
        if url.path == "/search":
            q = qs.get("q", [""])[0]
            return self._send([
                {"name": f"conda-{n}", "conda_name": n, "channel": ch, "add": f"{ch}::{n}", "summary": s,
                 "latest": v, "available": f"{v}-1" if State.added.get(n) == ch else None,
                 "shadowed_by": State.added[n] if n in State.added and State.added[n] != ch else None}
                for (ch, n), (v, s) in CATALOG.items() if q in n])
        if url.path == "/add":
            entries = [e for v in qs.get("name", []) for e in v.split(",")]
            added, bad = [], []
            for e in entries:
                ch, _, n = e.rpartition("::")
                ch, n = ch or "conda-forge", n.removeprefix("conda-")
                if (ch, n) in CATALOG:
                    State.added[n] = ch
                    added.append(f"conda-{n}")
                else:
                    bad.append(e)
            return self._send({"added": added, "failed": bad, "conflicts": [], "packages": len(State.added)})
        self._send({"error": "not found"}, 404)


def start() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
