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
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PORT = 8003
STATIC = Path(__file__).parent / "static"
RESULTS = Path("results")


def designs() -> list[dict]:
    return [{"name": p.parent.name, **json.loads(p.read_text())} for p in sorted(RESULTS.glob("*/run.json"))]


def files(folder: Path, *suffixes: str) -> list[Path]:
    """A target's files with these suffixes, without HyperLynx's board copies (each run's board/
    holds the whole project: slow to walk, and nothing to show)."""
    found = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != "board" and not d.startswith("."))
        found += [Path(root) / n for n in sorted(names) if n.endswith(suffixes)]
    return found


def design(name: str) -> dict:
    folder = RESULTS / name
    if not (folder / "run.json").is_file():
        raise FileNotFoundError(f"{name}: not run yet (layz run designs/{name})")
    run = json.loads((folder / "run.json").read_text())
    logged = (folder / "run.log").read_text(errors="replace").splitlines() if (folder / "run.log").exists() else []
    for t in run["targets"]:
        t["lines"] = logged[t["log"][0] : t["log"][1]] if t.get("log") else []
        out = folder / t["name"]
        t["tables"], t["plots"] = [], []
        if not out.is_dir():
            continue
        found = files(out, ".csv", ".png", ".overlay.json")
        for f in [f for f in found if f.suffix == ".csv" and f.stat().st_size < 64_000]:  # tables, not data dumps
            with open(f, newline="") as fh:
                rows = list(csv.reader(fh))
            if rows and len(rows) <= 400 and len(rows[0]) <= 30:  # tables, not data dumps
                t["tables"].append({"path": str(f.relative_to(folder)), "rows": rows})
        t["plots"] = [{"png": str(f.relative_to(folder)), "data": str(f.with_suffix(".plot.json").relative_to(folder)) if f.with_suffix(".plot.json").exists() else None} for f in found if f.suffix == ".png"]
        t["markers"] = json.loads((out / "markers.json").read_text()) if (out / "markers.json").exists() else None
        t["overlays"] = [str(f.relative_to(folder)) for f in found if f.name.endswith(".overlay.json")]
        t["summary"] = json.loads((out / "summary.json").read_text()) if (out / "summary.json").is_file() and (out / "summary.json").stat().st_size < 200_000 else None
    flow = Path(run.get("flow", ""))
    run["source"] = flow.read_text() if flow.is_file() else ""
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


def drawings(src: Path, folder: Path) -> dict[str, list[str]]:
    """KiCad's drawings of a schematic or board, dark and light, made once (again when the file
    is newer)."""
    from layz.web import layout as draw

    out = {}
    for theme in ("dark", "light"):
        where = folder.with_name(f"{folder.name}-{theme}")
        pages = sorted(where.glob("*.svg"))
        if not pages or pages[0].stat().st_mtime < src.stat().st_mtime:
            pages = draw.kicad_svg(src, where, dark=theme == "dark")
        out[theme] = ["/results/" + str(f.resolve().relative_to(RESULTS.resolve())) for f in pages]
    return out


def inputs(name: str) -> dict:
    """What a run's setup named, drawn: the layout (a GDS on its stack, or a board as SVG) and the
    schematic (SVG pages, or a netlist's nets); made once, kept in results/NAME/web/."""
    from layz.web import layout as draw

    run = json.loads((RESULTS / name / "run.json").read_text())
    i = run.get("inputs", {})
    web = RESULTS / name / "web"
    web.mkdir(parents=True, exist_ok=True)
    fresh = lambda cache, src: cache.exists() and cache.stat().st_mtime >= Path(src).stat().st_mtime
    out: dict = {"inputs": i}
    lay = Path(i.get("layout", ""))
    if lay.is_file() and lay.suffix.lower() in (".gds", ".gds2", ".oas") and i.get("stack"):
        cache = web / "layout.json"
        if not fresh(cache, lay):
            cache.write_text(json.dumps(draw.gds(lay, i["stack"])))
        out["layout"] = json.loads(cache.read_text())
    elif lay.is_file() and lay.suffix == ".kicad_pcb":
        out["layout_svgs"] = drawings(lay, web / "board")
    sch = Path(i.get("schematic", "")) if i.get("schematic") else (lay.with_suffix(".kicad_sch") if lay.suffix == ".kicad_pcb" else Path())
    if sch.is_file() and sch.suffix == ".kicad_sch":
        out["schematic_svgs"] = drawings(sch, web / "schematic")
        out["schematic_index"] = draw.schematic_index(sch)
    elif sch.is_file():
        out["netlist"] = draw.netlist(sch)
    return out


def flow_page(name: str) -> str:
    """The flow.py a design's last run ran, syntax-highlighted (highlight.js), dark or light as the
    system's."""
    import html

    run = json.loads((RESULTS / name / "run.json").read_text())
    flow = Path(run.get("flow", ""))
    code = html.escape(flow.read_text()) if flow.is_file() else "(not found)"
    hl = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(name)}: flow.py</title>
<link rel="stylesheet" href="{hl}/styles/nord.min.css" media="(prefers-color-scheme: dark)">
<link rel="stylesheet" href="{hl}/styles/github.min.css" media="(prefers-color-scheme: light)">
<script src="{hl}/highlight.min.js"></script>
<style>body {{ margin: 0; font: 13px/1.5 ui-monospace, "SF Mono", "Cascadia Mono", "DejaVu Sans Mono", Menlo, monospace; background: #2e3440; color: #d8dee9; }}
@media (prefers-color-scheme: light) {{ body {{ background: #fafafa; color: #242529; }} }}
header {{ padding: 12px 20px 0; opacity: 0.7; }} pre {{ margin: 0; }} code.hljs {{ padding: 12px 20px 40px; background: none; font: inherit; }}</style>
</head><body><header>{html.escape(str(flow))}</header><pre><code class="language-python">{code}</code></pre><script>hljs.highlightAll();</script></body></html>"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):  # quiet
        pass

    def end_headers(self):  # the page's own files too: a new layz shows at the next reload
        if "Cache-Control" not in "".join(h.decode(errors="replace") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

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
            if url.path == "/flow":  # a design's flow.py, highlighted, in a page of its own
                return self.send(200, flow_page(q["name"]).encode(), "text/html; charset=utf-8")
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
