"""A design's run as a page of files, without `layz web`: report.html in the run's folder, the viewer's page
with its data next to it (web/report/*.js next to it, each loaded when its view is opened), to
open from the file manager (a machine mounted over SFTP too) in a browser as it is."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from layz.web import server

STATIC = Path(__file__).parent / "static"


def write(folder: Path) -> Path:
    """Write FOLDER/report.html (FOLDER: a run's, with its run.json) and its data; the page's path."""
    folder = Path(folder)
    name = folder.name
    data = folder / "web" / "report"
    data.mkdir(parents=True, exist_ok=True)
    for old in data.glob("*.js"):
        old.unlink()
    design = server.design(name, folder)
    design.pop("source", None)  # the flow is its own page (web/flow.html)
    files: dict[str, str] = {}  # what the page asks for -> the script holding it

    def put(key: str, value) -> None:
        script = data / f"{len(files):03d}.js"
        script.write_text(f"LAYZ_PUT({json.dumps(key)}, {json.dumps(value)});\n")
        files[key] = str(script.relative_to(folder))

    try:
        inputs = server.inputs(name, folder, prefix="")
    except Exception as e:  # noqa: BLE001 (a drawing that can't be made: the page says so)
        inputs = {"inputs": design.get("inputs", {}), "error": str(e)}
    for key in ("layout_svgs", "schematic_svgs"):  # KiCad's drawings, per theme: the page's own paths
        for theme, urls in (inputs.get(key) or {}).items():
            for rel in urls:
                put(rel, (folder / rel).read_text(errors="replace"))
    put("api/inputs", inputs)
    try:
        put("api/board", server.board(name, folder))
    except FileNotFoundError:
        pass
    for t in design["targets"]:
        for rel in [p["data"] for p in t.get("plots", []) if p.get("data")] + t.get("overlays", []):
            put(rel, json.loads((folder / rel).read_text()))
    (folder / "web" / "flow.html").write_text(server.flow_page(name, folder))
    static = {"design": design, "files": files, "host": socket.getfqdn()}
    page = (STATIC / "index.html").read_text()
    blob = json.dumps(static).replace("</", "<\\/")
    page = page.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{(STATIC / 'style.css').read_text()}\n</style>")
    page = page.replace('<script src="app.js"></script>', f"<script>window.LAYZ_STATIC = {blob};</script>\n<script>\n{(STATIC / 'app.js').read_text()}\n</script>")
    page = page.replace("<title>layz runs</title>", f"<title>{name}</title>")
    out = folder / "report.html"
    out.write_text(page)
    return out
