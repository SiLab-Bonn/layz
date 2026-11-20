"""`layz web`: the runs of this clone's flows in a browser, on port 8003 (http://HOST:8003/).

Each `layz run designs/NAME` records itself in results/NAME/run.json (layz.flow); the page lists
those designs and shows one at a time: its targets with their status, the tables and plots each
target wrote into results/NAME/<target>/, and its board (the .hyp its setup named) with the
stackup, copper layer by layer, trace widths and vias.

    /                      the page (layz/web/static)
    /api/designs           every results/*/run.json
    /api/design?name=      one run, with each target's log lines, tables (CSV) and plots (PNG)
    /api/board?name=       its board, read from its .hyp (layz.web.board), cached next to the run
    /results/...           the files themselves
"""

from __future__ import annotations

import csv
import json
import mimetypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PORT = 8003
STATIC = Path(__file__).parent / "static"
RESULTS = Path("results")


def designs() -> list[dict]:
    return [{"name": p.parent.name, **json.loads(p.read_text())} for p in sorted(RESULTS.glob("*/run.json"))]


def design(name: str) -> dict:
    folder = RESULTS / name
    run = json.loads((folder / "run.json").read_text())
    logged = (folder / "run.log").read_text(errors="replace").splitlines() if (folder / "run.log").exists() else []
    for t in run["targets"]:
        t["lines"] = logged[t["log"][0] : t["log"][1]] if t.get("log") else []
        out = folder / t["name"]
        t["tables"], t["plots"] = [], []
        if not out.is_dir():
            continue
        for f in sorted(out.rglob("*.csv")):
            with open(f, newline="") as fh:
                rows = list(csv.reader(fh))
            if rows and len(rows) <= 400 and len(rows[0]) <= 30:  # tables, not data dumps
                t["tables"].append({"path": str(f.relative_to(folder)), "rows": rows})
        t["plots"] = [str(f.relative_to(folder)) for f in sorted(out.rglob("*.png"))]
    return {"name": name, **run}


def board(name: str) -> dict:
    from layz.web import board as boardfile

    run = json.loads((RESULTS / name / "run.json").read_text())
    hyp = Path(run.get("inputs", {}).get("board", ""))
    if not hyp.is_file():
        raise FileNotFoundError(f"{name}: no board yet (its setup names BOARD, the board target writes it)")
    cache = RESULTS / name / "board.json"
    if not cache.exists() or cache.stat().st_mtime < hyp.stat().st_mtime:
        cache.write_text(json.dumps(boardfile.read(hyp)))
    return json.loads(cache.read_text())


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):  # quiet
        pass

    def send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/designs":
                return self.send(200, json.dumps(designs()).encode(), "application/json")
            if url.path == "/api/design":
                return self.send(200, json.dumps(design(q["name"])).encode(), "application/json")
            if url.path == "/api/board":
                return self.send(200, json.dumps(board(q["name"])).encode(), "application/json")
            if url.path.startswith("/results/"):
                f = (RESULTS / unquote(url.path[len("/results/") :])).resolve()
                if RESULTS.resolve() not in f.parents or not f.is_file():
                    return self.send(404, b"not found", "text/plain")
                return self.send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        except (FileNotFoundError, KeyError) as e:
            return self.send(404, json.dumps({"error": str(e)}).encode(), "application/json")
        return super().do_GET()


def main() -> int:
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"layz web: http://localhost:{PORT}/ (the runs in {RESULTS.resolve()}); Ctrl-C stops it", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
