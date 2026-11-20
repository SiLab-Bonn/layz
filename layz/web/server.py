"""`layz web`: the runs of this clone's flows in a browser, on port 8003 (http://HOST:8003/).

Each `layz run designs/NAME` records itself in results/NAME/run.json (layz.flow); the first page
lists those designs, and one opens as a single page, top to bottom in the flow's order: the
inputs its setup named (layout layer by layer with its stackup, schematic), then each target
with its tables, plots and log; the board target with the board HyperLynx simulates (copper,
stackup, trace widths, vias).

    /                      the page (layz/web/static)
    /api/designs           every results/*/run.json
    /api/design?name=      one run, with each target's log lines, tables (CSV) and plots (PNG)
    /api/inputs?name=      its inputs drawn: the layout (a GDS on its stack, a board as SVG), the schematic
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


def inputs(name: str) -> dict:
    """What a run's setup named, drawn: the layout (a GDS on its stack, or a board as SVG) and the
    schematic (SVG pages, or a netlist's nets); made once, kept in results/NAME/web/."""
    from layz.web import layout as draw

    run = json.loads((RESULTS / name / "run.json").read_text())
    i = run.get("inputs", {})
    web = RESULTS / name / "web"
    web.mkdir(parents=True, exist_ok=True)
    url = lambda f: "/results/" + str(Path(f).resolve().relative_to(RESULTS.resolve()))
    fresh = lambda cache, src: cache.exists() and cache.stat().st_mtime >= Path(src).stat().st_mtime
    out: dict = {"inputs": i}
    lay = Path(i.get("layout", ""))
    if lay.is_file() and lay.suffix.lower() in (".gds", ".gds2", ".oas") and i.get("stack"):
        cache = web / "layout.json"
        if not fresh(cache, lay):
            cache.write_text(json.dumps(draw.gds(lay, i["stack"])))
        out["layout"] = json.loads(cache.read_text())
    elif lay.is_file() and lay.suffix == ".kicad_pcb":
        pages = sorted((web / "board").glob("*.svg")) if fresh(web / "board" / "board.svg", lay) else draw.kicad_svg(lay, web / "board")
        out["layout_svgs"] = [url(f) for f in pages]
    sch = Path(i.get("schematic", "")) if i.get("schematic") else (lay.with_suffix(".kicad_sch") if lay.suffix == ".kicad_pcb" else Path())
    if sch.is_file() and sch.suffix == ".kicad_sch":
        pages = sorted((web / "schematic").glob("*.svg"))
        if not pages or pages[0].stat().st_mtime < sch.stat().st_mtime:
            pages = draw.kicad_svg(sch, web / "schematic")
        out["schematic_svgs"] = [url(f) for f in pages]
    elif sch.is_file():
        out["netlist"] = draw.netlist(sch)
    return out


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
            if url.path == "/api/inputs":
                return self.send(200, json.dumps(inputs(q["name"])).encode(), "application/json")
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
