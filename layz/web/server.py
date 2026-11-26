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
REPO = Path(__file__).resolve().parents[2]  # this clone: its flows and stacks can be previewed
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


def design(name: str, folder: Path | None = None) -> dict:
    """A run (in results/NAME, or ``folder``) with what each target wrote."""
    folder = folder or RESULTS / name
    if not (folder / "run.json").is_file():
        raise FileNotFoundError(f"{name}: not run yet (layz run designs/{name})")
    run = json.loads((folder / "run.json").read_text())
    logged = (folder / "run.log").read_text(errors="replace").splitlines() if (folder / "run.log").exists() else []
    for t in run["targets"]:
        t["lines"] = logged[t["log"][0] : t["log"][1]] if t.get("log") else []
        out = folder / t["name"]
        if t["lines"] and not (out / "log.txt").exists():  # runs from before each step wrote its own
            out.mkdir(parents=True, exist_ok=True)
            (out / "log.txt").write_text("\n".join(t["lines"]) + "\n")
        t["tables"], t["plots"] = [], []
        if not out.is_dir():
            continue
        found = files(out, ".csv", ".png", ".overlay.json")
        for f in sorted((f for f in found if f.suffix == ".csv" and f.parent == out and f.stat().st_size < 64_000), key=lambda f: f.stat().st_mtime):  # in the order the flow wrote them  # its own tables (a run's raw files below are not), not data dumps
            with open(f, newline="") as fh:
                rows = list(csv.reader(fh))
            if rows and len(rows) <= 400 and len(rows[0]) <= 30:  # tables, not data dumps
                t["tables"].append({"path": str(f.relative_to(folder)), "rows": rows})
        t["plots"] = [{"png": str(f.relative_to(folder)), "data": str(f.with_suffix(".plot.json").relative_to(folder)) if f.with_suffix(".plot.json").exists() else None} for f in sorted((f for f in found if f.suffix == ".png"), key=lambda f: f.stat().st_mtime)]  # in the order the flow made them
        t["markers"] = json.loads((out / "markers.json").read_text()) if (out / "markers.json").exists() else None
        t["overlays"] = [str(f.relative_to(folder)) for f in found if f.name.endswith(".overlay.json")]
        # what the step wrote, for sftp:// links (its own files, not HyperLynx's board copies)
        t["folder"] = str(out.resolve())
        found_files = sorted(str(f.relative_to(out)) for f in files(out, "") if not f.name.endswith((".plot.json", ".overlay.json")) and f.name != "job.json")
        t["files"] = (["log.txt"] if "log.txt" in found_files else []) + [f for f in found_files if f != "log.txt"][:60]  # the log first
        t["summary"] = json.loads((out / "summary.json").read_text()) if (out / "summary.json").is_file() and (out / "summary.json").stat().st_size < 200_000 else None
    flow = Path(run.get("flow", ""))
    run["source"] = flow.read_text() if flow.is_file() else ""
    run["root"] = str(folder.resolve())
    # the inputs' and the flow's files, absolute (a stack named by its process: its stack file)
    from layz import stack as stackfile

    paths = {"flow": run.get("flow", "")}
    for k, v in run.get("inputs", {}).items():
        try:
            paths[k] = str(stackfile.resolve(v).resolve()) if k == "stack" else str(Path(v).resolve())
        except FileNotFoundError:
            paths[k] = ""
    run["paths"] = paths
    return {"name": name, **run}


def board(name: str, folder: Path | None = None) -> dict:
    from layz.web import board as boardfile

    folder = folder or RESULTS / name
    run = json.loads((folder / "run.json").read_text())
    hyp = Path(run.get("board") or run.get("inputs", {}).get("board", ""))
    if not hyp.is_file():
        raise FileNotFoundError(f"{name}: no board yet (its setup names BOARD, the board target writes it)")
    cache = folder / "board.json"
    if not cache.exists() or cache.stat().st_mtime < hyp.stat().st_mtime:
        cache.write_text(json.dumps(boardfile.read(hyp)))
    b = json.loads(cache.read_text())
    facts = folder / "facts.json"  # its facts table (layz.web.facts), with the run's stack and GDS
    if not facts.exists() or facts.stat().st_mtime < cache.stat().st_mtime:
        from layz import stack as stackfile
        from layz.web import facts as boardfacts

        i = run.get("inputs", {})
        try:
            process = stackfile.load(i["stack"]) if i.get("stack") else None
        except (FileNotFoundError, KeyError):
            process = None
        facts.write_text(json.dumps(boardfacts.board(b, process, Path(i["layout"]) if i.get("layout") else None)))
    b["facts"] = json.loads(facts.read_text())
    return b


def drawings(src: Path, folder: Path, root: Path, prefix: str) -> dict[str, list[str]]:
    """KiCad's drawings of a schematic or board, dark and light, made once (again when the file
    is newer); each as ``prefix`` + its path in the run's folder ``root``."""
    from layz.web import layout as draw

    out = {}
    for theme in ("dark", "light"):
        where = folder.with_name(f"{folder.name}-{src.stem}-{theme}")  # per source: another file, another drawing
        pages = sorted(where.glob("*.svg"))
        if not pages or pages[0].stat().st_mtime < src.stat().st_mtime:
            pages = draw.kicad_svg(src, where, dark=theme == "dark")
        out[theme] = [prefix + str(f.resolve().relative_to(root.resolve())) for f in pages]
    return out


def inputs(name: str, folder: Path | None = None, prefix: str | None = None) -> dict:
    """What a run's setup named, drawn: the layout (a GDS on its stack, or a board as SVG) and the
    schematic (SVG pages, or a netlist's nets); made once, kept in results/NAME/web/."""
    from layz.web import layout as draw

    folder = folder or RESULTS / name
    prefix = f"/results/{name}/" if prefix is None else prefix  # the drawings' paths: served, or the folder's own
    run = json.loads((folder / "run.json").read_text())
    i = run.get("inputs", {})
    web = folder / "web"
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
        # a KiCad board: drawn from the run's HyperLynx board of it (copper per layer, vias, its
        # stackup), as a GDS is; KiCad's own drawing until there is one
        if Path(run.get("board") or i.get("board", "")).is_file():
            out["layout"] = board(name, folder)
        else:
            out["layout_svgs"] = drawings(lay, web / "board", folder, prefix)
    sch = Path(i.get("schematic", "")) if i.get("schematic") else (lay.with_suffix(".kicad_sch") if lay.suffix == ".kicad_pcb" else Path())
    if sch.is_file() and sch.suffix == ".kicad_sch":
        out["schematic_svgs"] = drawings(sch, web / "schematic", folder, prefix)
        out["schematic_index"] = draw.schematic_index(sch)
    elif sch.is_file():
        out["netlist"] = draw.netlist(sch)
    return out


def flow_page(name: str, folder: Path | None = None) -> str:
    """The flow.py a design's last run ran, syntax-highlighted (highlight.js), dark or light as the
    system's."""
    import html

    run = json.loads(((folder or RESULTS / name) / "run.json").read_text())
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
            if url.path == "/file":  # a file of a run, or of this clone (flows, stacks), to look at
                f = Path(q["path"]).resolve()
                if not f.is_file() or not any(root in f.parents for root in (RESULTS.resolve(), REPO)):
                    return self.send(404, b"not found", "text/plain")
                kind = mimetypes.guess_type(f.name)[0] or ""
                shown = kind if kind.startswith("image/") or kind == "application/pdf" else "text/plain; charset=utf-8"
                return self.send(200, f.read_bytes(), shown)
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
