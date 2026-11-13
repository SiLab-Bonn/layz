#!/usr/bin/env python3
"""3-D electrostatic field solve (capacitance matrix) of GDS geometry.

Pipeline:
    GDS + stack TOML -> KLayout connectivity -> conductor bodies
        -> KLayout-PEX FasterCapModelBuilder (3-D extrusion, dielectric interfaces, mesh)
        -> .lst/.geo -> FasterCap or FastCap2 -> capacitance matrix (CSV, fF)

KiCad boards go through kicad2fastercap.py, which reuses this module's flow (run_flow).

No LVS and no netlist are involved: a conductor is every set of shapes that touch,
or are joined by vias. Name conductors with texts on the conductor layer or with
--name NAME=LAYER@X,Y; unnamed bodies are numbered n1, n2, ... and listed with their location.

Run in the repo's venv (see README):
    layz pex example_files/conv_test_2.gds --stack stacks/<process>.toml
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import klayout.db as db

from layz import solvers

MODEL_DBU_UM = 0.001  # 1 nm model grid; kpex's builder snaps z to the dbu


# --------------------------------------------------------------------------- stack


@dataclass
class Conductor:
    name: str
    layer: str  # "L/D" for GDS, KiCad layer name for KiCad JSON
    z: float  # bottom, µm
    thickness: float  # µm
    labels: list[str] = field(default_factory=list)  # extra text layers naming nets


@dataclass
class Via:
    name: str
    layer: str
    bottom: str | None
    top: str | None
    z: float
    thickness: float


@dataclass
class Dielectric:
    name: str
    k: float
    z: float
    thickness: float


@dataclass
class Stack:
    k_void: float
    halo_um: float
    conductors: list[Conductor]
    vias: list[Via]
    dielectrics: list[Dielectric]

    @classmethod
    def from_dict(cls, d: dict) -> Stack:
        conds = [
            Conductor(
                name=c["name"],
                layer=str(c["layer"]),
                z=float(c["z"]),
                thickness=float(c["thickness"]),
                labels=[str(x) for x in c.get("labels", [])],
            )
            for c in d.get("conductor", [])
        ]
        by_name = {c.name: c for c in conds}
        vias = []
        for v in d.get("via", []):
            bot, top = v.get("bottom"), v.get("top")
            if "z" in v:
                z0 = float(v["z"])
            elif bot in by_name:
                z0 = by_name[bot].z + by_name[bot].thickness
            else:
                raise ValueError(f"via {v['name']}: give 'z' or a known 'bottom' conductor")
            if "thickness" in v:
                t = float(v["thickness"])
            elif top in by_name:
                t = by_name[top].z - z0
            else:
                raise ValueError(f"via {v['name']}: give 'thickness' or a known 'top' conductor")
            if t <= 0:
                raise ValueError(f"via {v['name']}: non-positive height {t} µm")
            vias.append(Via(v["name"], str(v["layer"]), bot, top, z0, t))
        diels = [
            Dielectric(x["name"], float(x["k"]), float(x["z"]), float(x["thickness"]))
            for x in d.get("dielectric", [])
        ]
        return cls(
            k_void=float(d.get("k_void", 1.0)),
            halo_um=float(d.get("halo_um", 100.0)),
            conductors=conds,
            vias=vias,
            dielectrics=diels,
        )


def stack_from_process(p, gds: bool, via_spans: set[tuple[str, str]] | None = None) -> Stack:
    """A layz process stack (layz.stack.Process) as the 3-D model's stack (µm, z = bottom).

    Copper layers become conductors; each copper layer's own z range is filled, between the
    copper, by a neighbouring dielectric (outer copper by the mask, inner copper by the thinner
    neighbour); slabs of one material that touch in z are merged (the model builder sees
    overlaps otherwise). Conductors are keyed by GDS layer (gds=True) or by copper name (KiCad).
    Vias: the process's [[via]] layers (gds=True), or barrels spanning `via_spans`
    (top, bottom) copper pairs, keyed "V:top:bottom" (KiCad boards).
    """
    items = p.layers
    conductors, slabs = [], []
    for i, l in enumerate(items):
        if l.type == "copper":
            if gds and not l.gds:
                continue
            conductors.append(Conductor(name=l.name, layer=l.gds if gds else l.name,
                                        z=l.z_um, thickness=l.thickness_um))
            nbrs = [items[j] for j in (i - 1, i + 1) if 0 <= j < len(items) and items[j].type != "copper"]
            nbrs.sort(key=lambda n: (0 if n.type == "mask" else 1, n.thickness_um))
            if nbrs:
                slabs.append([_material_key(nbrs[0]), nbrs[0].k, l.z_um, l.thickness_um])
        else:
            slabs.append([_material_key(l), l.k, l.z_um, l.thickness_um])
    slabs.sort(key=lambda d: (d[0], d[2]))
    merged: list[list] = []
    for name, k, z0, t in slabs:
        if merged and merged[-1][0] == name and abs(merged[-1][2] + merged[-1][3] - z0) < 1e-6:
            merged[-1][3] += t
        else:
            merged.append([name, k, z0, t])
    dielectrics = [Dielectric(name=n, k=k, z=z0, thickness=t)
                   for n, k, z0, t in sorted(merged, key=lambda d: -d[2])]

    by = {c.name: c for c in conductors}
    vias = []
    if gds:
        for v in p.vias:
            if v.top in by and v.bottom in by:
                b, t = by[v.bottom], by[v.top]
                vias.append(Via(name=f"V_{v.gds.replace('/', '_')}", layer=v.gds, bottom=v.bottom,
                                top=v.top, z=b.z + b.thickness, thickness=t.z - (b.z + b.thickness)))
    else:
        for top, bot in sorted(via_spans or ()):
            b, t = by[bot], by[top]
            vias.append(Via(name=f"V_{top}_{bot}".replace(".", ""), layer=f"V:{top}:{bot}",
                            bottom=bot, top=top, z=b.z, thickness=t.z + t.thickness - b.z))
    return Stack(k_void=1.0, halo_um=p.halo_um, conductors=conductors, vias=vias,
                 dielectrics=dielectrics)


def _material_key(l) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", l.name)


# --------------------------------------------------------------------------- geometry input


def layer_info(spec: str) -> db.LayerInfo:
    m = re.fullmatch(r"(\d+)/(\d+)", spec)
    return db.LayerInfo(int(m[1]), int(m[2])) if m else db.LayerInfo(spec)


def find_or_make_layer(layout: db.Layout, spec: str) -> int:
    info = layer_info(spec)
    li = layout.find_layer(info)
    return li if li is not None else layout.layer(info)


def load_gds(path: Path, cell: str | None) -> tuple[db.Layout, db.Cell]:
    layout = db.Layout()
    layout.read(str(path))
    top = layout.cell(cell) if cell else layout.top_cell()
    if top is None:
        raise SystemExit(f"cell {cell!r} not found in {path}")
    return layout, top


def to_model_grid(layout: db.Layout) -> None:
    """Rescale to a 1 nm database unit, so z values aren't snapped to e.g. 1 µm."""
    factor = layout.dbu / MODEL_DBU_UM
    if abs(factor - 1.0) < 1e-9:
        return
    if abs(factor - round(factor)) > 1e-6:
        raise SystemExit(f"dbu {layout.dbu} µm is not a multiple of 1 nm")
    layout.transform(db.ICplxTrans(round(factor)))
    layout.dbu = MODEL_DBU_UM


# --------------------------------------------------------------------------- connectivity


@dataclass
class Body:
    name: str
    parts: list[tuple[str, db.Region, float, float]]  # (stack layer, region, z, height)

    def bbox(self) -> db.Box:
        b = db.Box()
        for _, r, _, _ in self.parts:
            b += r.bbox()
        return b


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", name).strip("_") or "net"


def extract_bodies(layout: db.Layout, top: db.Cell, stack: Stack,
                   ports: list[tuple[str, str, float, float]],
                   merge_names: bool = True) -> list[Body]:
    cond_by_name = {c.name: c for c in stack.conductors}

    # CLI ports become texts on a per-conductor port layer
    port_layers: dict[str, int] = {}
    for name, cond, x, y in ports:
        if cond not in cond_by_name:
            raise SystemExit(f"--name {name}: unknown conductor {cond!r} "
                             f"(stack has {', '.join(cond_by_name)})")
        li = port_layers.setdefault(cond, layout.layer(db.LayerInfo(f"__port_{cond}")))
        p = db.DPoint(x, y)
        top.shapes(li).insert(db.DText(name, db.DTrans(p)))

    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))
    regions: dict[str, db.Region] = {}

    for c in stack.conductors:
        regions[c.name] = l2n.make_polygon_layer(find_or_make_layer(layout, c.layer), c.name)
        l2n.connect(regions[c.name])
        text_specs = [c.layer, f"{c.layer}.net", *c.labels]
        for i, spec in enumerate(text_specs):
            li = layout.find_layer(layer_info(spec))
            if li is None:
                continue
            t = l2n.make_text_layer(li, f"{c.name}__t{i}")
            l2n.connect(regions[c.name], t)
        if c.name in port_layers:
            t = l2n.make_text_layer(port_layers[c.name], f"{c.name}__ports")
            l2n.connect(regions[c.name], t)

    for v in stack.vias:
        regions[v.name] = l2n.make_polygon_layer(find_or_make_layer(layout, v.layer), v.name)
        l2n.connect(regions[v.name])
        # a via connects every conductor layer its z range touches or passes through
        # (e.g. the inner-layer rings of a through via), plus its named ends
        v_top = v.z + v.thickness
        for c in stack.conductors:
            if c.name in (v.bottom, v.top) or (c.z <= v_top + 1e-6 and c.z + c.thickness >= v.z - 1e-6):
                l2n.connect(regions[v.name], regions[c.name])

    l2n.extract_netlist()
    circuit = l2n.netlist().circuit_by_name(top.name)
    if circuit is None:
        return []

    bodies: list[Body] = []
    auto = 0
    for net in circuit.each_net():
        parts = []
        for c in stack.conductors:
            r = l2n.shapes_of_net(net, regions[c.name], True)
            if not r.is_empty():
                parts.append((c.name, r.merged(), c.z, c.thickness))
        for v in stack.vias:
            r = l2n.shapes_of_net(net, regions[v.name], True)
            if not r.is_empty():
                parts.append((v.name, r.merged(), v.z, v.thickness))
        if not parts:
            continue
        name = net.name
        if not name or name.startswith("$"):
            auto += 1
            name = f"n{auto}"
        elif "," in name:
            print(f"warning: one body carries several names {name!r}; they are shorted",
                  file=sys.stderr)
        bodies.append(Body(sanitize(name), parts))

    if merge_names:
        # bodies carrying the same name (e.g. a KiCad net that the copper leaves in pieces)
        # are held at one potential: one conductor in the solve
        merged: dict[str, Body] = {}
        for b in bodies:
            if b.name in merged and not re.fullmatch(r"n\d+", b.name):
                merged[b.name].parts += b.parts
            else:
                merged.setdefault(b.name, b)
        bodies = list(merged.values())

    # unique names
    seen: dict[str, int] = {}
    for b in bodies:
        if b.name in seen:
            seen[b.name] += 1
            b.name = f"{b.name}_{seen[b.name]}"
        else:
            seen[b.name] = 0
    return bodies


# --------------------------------------------------------------------------- model + solve


_delaunay = db.Region.delaunay
SLIVERS_DROPPED = 0
SNAPPED = 0


def _at_origin(region: db.Region, *args) -> db.Region:
    """Triangulate relative to the region's own corner and move the triangles back: exact (an
    integer move), and it keeps KLayout's triangulator in a coordinate range where it can resolve
    near-duplicate vertices (it fails on a clean 166 x 150 mm board plane at ~3e8 nm otherwise)."""
    bb = region.bbox()
    return _delaunay(region.moved(-bb.left, -bb.bottom), *args).moved(bb.left, bb.bottom)


def _trapezoid_triangles(region: db.Region) -> db.Region:
    """Triangles without the triangulator: KLayout's trapezoid decomposition (handles holes and
    any coordinates), each trapezoid cut in two. A coarse mesh, which FasterCap refines anyway."""
    out = db.Region()
    for p in region.each():
        for t in p.decompose_trapezoids():
            pts = list(t.each_point())
            # drop repeated points (a trapezoid with a zero-length top/bottom is a triangle)
            pts = [q for i, q in enumerate(pts) if q != pts[i - 1]]
            for i in range(1, len(pts) - 1):
                tri = db.Polygon([pts[0], pts[i], pts[i + 1]])
                if tri.area() > 0:
                    out.insert(tri)
    return out


def _robust_delaunay(self: db.Region, *args):
    """KLayout's triangulator (Region.delaunay) with fallbacks for the inputs it rejects:
    1. as is; 2. relative to the region's corner (it fails on near-duplicate vertices at large
    absolute coordinates, e.g. a 166 x 150 mm board plane); 3. the same without the minimum-angle
    criterion; 4. polygon by polygon, sub-2 nm slivers dropped (two polygonizations of one round
    pad that disagree), each at its own origin, and a polygon still rejected is split into
    trapezoids (exact geometry, coarser mesh)."""
    global SLIVERS_DROPPED, SNAPPED
    for attempt in (lambda: _delaunay(self, *args), lambda: _at_origin(self, *args),
                    lambda: _at_origin(self, args[0], 0.0)):
        try:
            return attempt()
        except RuntimeError:
            pass
    out = db.Region()
    for p in self.each():
        if 2 * p.area() / max(p.perimeter(), 1) < 2:
            SLIVERS_DROPPED += 1
            continue
        one = db.Region(p)
        try:
            out += _at_origin(one, *args)
        except RuntimeError:
            SNAPPED += 1
            out += _trapezoid_triangles(one)
    return out


db.Region.delaunay = _robust_delaunay


def build_model(bodies: list[Body], stack: Stack, amax_um2: float, delaunay_b: float):
    from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder

    mb = FasterCapModelBuilder(dbu=MODEL_DBU_UM, k_void=stack.k_void,
                               delaunay_amax=amax_um2, delaunay_b=delaunay_b)
    bbox = db.Box()
    for b in bodies:
        bbox += b.bbox()
        for _, region, z, h in b.parts:
            mb.add_conductor(net_name=b.name, layer=region, z=z, height=h, group_name=b.name)

    halo = round(stack.halo_um / MODEL_DBU_UM)
    slab = db.Region(bbox.enlarged(halo, halo))
    for d in stack.dielectrics:
        mb.add_material(name=d.name, k=d.k)
    for d in stack.dielectrics:
        mb.add_dielectric(material_name=d.name, layer=slab, z=d.z, height=d.thickness)
    return mb.generate()


@dataclass
class CapacitanceMatrix:
    """A solver's capacitance matrix: conductor names and rows, in F."""
    conductor_names: list[str]
    rows: list[list[float]]

    def __getitem__(self, i):
        return self.rows[i]


# FasterCap 6.2 exit codes (iic-jku fork); earlier versions exit 0 or 1
FASTERCAP_EXIT = {1: "other error", 64: "wrong command line", 65: "NaN or infinite results",
                  66: "input file can't be opened", 71: "out of memory", 74: "input can't be read",
                  75: "GMRES didn't converge", 97: "can't go out-of-core", 98: "unexpected exception",
                  125: "stopped"}


def run_solver(args, lst: Path, log: Path) -> CapacitanceMatrix:
    """Run FasterCap or FastCap2 on the model's .lst in its own folder; the log goes to `log`.

    layz starts the solvers itself (only KLayout-PEX's 3-D model builder is used from it), so a
    newer KLayout-PEX can't change how the solvers are called or read."""
    import subprocess

    if args.solver == "fastercap":
        cmd = [solvers.find("fastercap"), "-b", "-i", f"-a{args.tolerance}", f"-d{args.d_coeff}",
               f"-m{args.mesh}", "-ap", *(["-c"] if args.charges else []),
               *(["-g"] if args.galerkin else []), lst.name]
    else:
        cmd = [solvers.find("fastcap2"), "-o2", "-p1.0", f"-t{args.tolerance}", f"-l{lst.name}"]
    with open(log, "w") as f:
        rc = subprocess.run(cmd, cwd=lst.parent, stdin=subprocess.DEVNULL, stdout=f,
                            stderr=subprocess.STDOUT).returncode
    if rc != 0:
        why = FASTERCAP_EXIT.get(rc, "") if args.solver == "fastercap" else ""
        raise SystemExit(f"{cmd[0]} failed with exit code {rc}{f' ({why})' if why else ''}, see {log}")
    return parse_fastercap(log) if args.solver == "fastercap" else parse_fastcap2(log)


def parse_fastercap(log: Path) -> CapacitanceMatrix:
    """Last capacitance matrix of a FasterCap log, in F (geometry in µm, the solver assumes m).

        Capacitance matrix is:
        Dimension 2 x 2
        g1_bot  9.21794e-07 -9.01492e-07
        g2_top  -9.01492e-07 9.21794e-07
    """
    lines = log.read_text(errors="replace").splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip() == "Capacitance matrix is:"]
    if not starts:
        raise SystemExit(f"no capacitance matrix in {log}")
    i = starts[-1]
    m = re.match(r"Dimension (\d+) x (\d+)", lines[i + 1].strip())
    if not m:
        raise SystemExit(f"can't read the matrix dimension in {log}")
    names, rows = [], []
    for line in lines[i + 2:i + 2 + int(m.group(1))]:
        cells = line.split()
        names.append(cells[0])
        rows.append([float(c) * 1e-6 for c in cells[1:]])
    return CapacitanceMatrix(conductor_names=names, rows=rows)


FASTCAP2_UNITS = {"farads": 1.0, "millifarads": 1e-3, "microfarads": 1e-6,
                  "nanofarads": 1e-9, "picofarads": 1e-12, "femtofarads": 1e-15,
                  "attofarads": 1e-18}


def parse_fastcap2(log: Path) -> CapacitanceMatrix:
    """Last capacitance matrix of a FastCap2 log, in F (geometry in µm, solver assumes m)."""
    lines = log.read_text(errors="replace").splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith("CAPACITANCE MATRIX, ")]
    if not starts:
        raise SystemExit(f"no capacitance matrix in {log}")
    i = starts[-1]
    scale = FASTCAP2_UNITS[lines[i].split(",")[1].strip().lower()] * 1e-6
    dim = len(lines[i + 1].split())
    names, rows = [], []
    for line in lines[i + 2:i + 2 + dim]:
        cells = line.split()
        names.append(cells[0])
        rows.append([float(c) * scale for c in cells[2:]])  # cells[1] is the row index
    return CapacitanceMatrix(conductor_names=names, rows=rows)


def clean_name(raw: str) -> str:
    # FasterCap reports "g1_NAME" style names, FastCap2 "1%NAME" / "NAME%GROUPn"
    s = re.sub(r"^g\d+_", "", raw)
    s = re.sub(r"%GROUP\d+$", "", s)
    s = re.sub(r"^\$?\d+%", "", s)
    return s


def report(cm, bodies: list[Body], out: Path) -> None:
    names = [clean_name(n) for n in cm.conductor_names]
    n = len(names)
    # symmetrize, convert F -> fF
    C = [[0.5 * (cm[i][j] + cm[j][i]) * 1e15 for j in range(n)] for i in range(n)]

    with open(out / "maxwell_matrix_fF.csv", "w") as f:
        f.write("," + ",".join(names) + "\n")
        for i in range(n):
            f.write(names[i] + "," + ",".join(f"{v:.6g}" for v in C[i]) + "\n")

    # SPICE / "mutual" view: C_ij = -Maxwell_ij, C_i,inf = row sum
    with open(out / "spice_caps_fF.csv", "w") as f:
        f.write("a,b,C_fF\n")
        for i in range(n):
            f.write(f"{names[i]},INF,{sum(C[i]):.6g}\n")
            for j in range(i + 1, n):
                f.write(f"{names[i]},{names[j]},{-C[i][j]:.6g}\n")

    w = max(8, *(len(x) for x in names))
    print("\nMaxwell capacitance matrix [fF] (diagonal = total, off-diagonal = -mutual):")
    print(" " * w + "".join(f"{x:>{w + 2}}" for x in names))
    for i in range(n):
        print(f"{names[i]:<{w}}" + "".join(f"{v:>{w + 2}.4g}" for v in C[i]))
    print("\nTo infinity (row sums) [fF]:")
    for i in range(n):
        print(f"  {names[i]:<{w}} {sum(C[i]):.4g}")
    print(f"\nwrote {out / 'maxwell_matrix_fF.csv'} and {out / 'spice_caps_fF.csv'}")


# --------------------------------------------------------------------------- CLI


def parse_port(text: str) -> tuple[str, str, float, float]:
    m = re.fullmatch(r"([^=]+)=([^@]+)@(-?[\d.eE+-]+),(-?[\d.eE+-]+)", text)
    if not m:
        raise argparse.ArgumentTypeError("expected NAME=CONDUCTOR@X,Y (µm)")
    return m[1], m[2], float(m[3]), float(m[4])


def add_flow_args(ap: argparse.ArgumentParser) -> None:
    """Options shared by fieldsolve.py (GDS) and kicad2fastercap.py (KiCad)."""
    ap.add_argument("--split-nets", action="store_true",
                    help="keep disconnected bodies of the same name as separate conductors")
    ap.add_argument("--nets", help="comma-separated body names to keep (default: all)")
    ap.add_argument("--solver", choices=["fastercap", "fastcap2"], default="fastercap")
    ap.add_argument("--out", type=Path, help="run directory (default: run_<input stem>)")
    ap.add_argument("--amax", type=float, default=None,
                    help="max triangle area µm² (default: 0 = FasterCap refines itself; "
                         "for fastcap2 bbox/2000)")
    ap.add_argument("--delaunay-b", type=float, default=0.5)
    ap.add_argument("--tolerance", type=float, default=0.01,
                    help="relative tolerance (keep <= 0.01 with dielectrics)")
    ap.add_argument("--mesh", type=float, default=0.5, help="FasterCap -m refinement")
    ap.add_argument("--d-coeff", type=float, default=0.5, help="FasterCap -d coefficient")
    ap.add_argument("--galerkin", action="store_true", help="FasterCap Galerkin scheme")
    ap.add_argument("--charges", action="store_true",
                    help="FasterCap: also dump panel charges, for fieldview.py (E-field, potential)")
    ap.add_argument("--stl", action="store_true", help="also dump STL of each body/dielectric")
    ap.add_argument("--list", action="store_true", help="only list the conductor bodies")
    ap.add_argument("--dry-run", action="store_true", help="write solver input, don't solve")
    ap.add_argument("-v", "--verbose", action="store_true")


def setup_logging(verbose: bool) -> None:
    """Quiet KLayout-PEX's model builder unless -v (its logging API is internal: best effort)."""
    try:
        from klayout_pex.log import LogLevel, set_log_level
        from klayout_pex.log.logger import configure_logger
        configure_logger()
        set_log_level(LogLevel.SUBPROCESS if verbose else LogLevel.WARNING)
    except (ImportError, AttributeError):
        pass


def run_flow(args, layout: db.Layout, top: db.Cell, stack: Stack, out: Path,
             ports: list[tuple[str, str, float, float]] = ()) -> None:
    """Conductor bodies -> 3-D model (.lst/.geo) -> FasterCap/FastCap2 -> capacitance matrix."""
    to_model_grid(layout)
    bodies = extract_bodies(layout, top, stack, list(ports), merge_names=not args.split_nets)
    if args.nets:
        keep = set(args.nets.split(","))
        bodies = [b for b in bodies if b.name in keep]
    if not bodies:
        raise SystemExit("no conductor bodies found: check the layer mapping")

    print(f"{len(bodies)} conductor bodies:")
    for b in bodies:
        bb = b.bbox()
        layers = sorted({p[0] for p in b.parts})
        print(f"  {b.name:<16} layers={','.join(layers):<20} "
              f"bbox=({bb.left * MODEL_DBU_UM:.1f},{bb.bottom * MODEL_DBU_UM:.1f};"
              f"{bb.right * MODEL_DBU_UM:.1f},{bb.top * MODEL_DBU_UM:.1f}) µm")
    if args.list:
        return

    amax = args.amax
    if amax is None:
        if args.solver == "fastcap2":
            bb = db.Box()
            for b in bodies:
                bb += b.bbox()
            amax = bb.width() * bb.height() * MODEL_DBU_UM ** 2 / 2000
        else:
            amax = 0.0

    out.mkdir(parents=True, exist_ok=True)
    gen = build_model(bodies, stack, amax, args.delaunay_b)
    if gen is None:
        raise SystemExit("empty model")
    if SLIVERS_DROPPED:
        print(f"note: dropped {SLIVERS_DROPPED} sub-2 nm sliver polygon(s) the triangulator rejected")
    if SNAPPED:
        print(f"note: {SNAPPED} polygon(s) meshed from trapezoids (the triangulator rejected them); "
              "exact geometry, coarser start mesh")
    files = gen.write_fastcap(str(out), prefix="m")
    lst = Path(files[0])
    print(f"solver input: {lst} ({len(files) - 1} panel files)")
    if args.stl:
        stls = gen.dump_stl(str(out), prefix="stl_")
        print(f"STL: {len(stls)} files in {out}")
    if args.dry_run:
        return

    cm = run_solver(args, lst, out / f"{args.solver}.log")
    if args.solver == "fastercap":
        passes = (out / "fastercap.log").read_text().count("Iteration number")
        if passes < 2:
            print(f"WARNING: FasterCap stopped after {passes} refinement pass(es); with dielectrics "
                  f"the first pass can be far off (e.g. 35 % low). Lower --tolerance "
                  f"(now {args.tolerance}) and compare.", file=sys.stderr)
    report(cm, bodies, out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", type=Path, help="GDS or OASIS file")
    ap.add_argument("--stack", type=Path, required=True,
                    help="layz process stack (.toml, see stacks/ and layz/stack.py)")
    ap.add_argument("--cell", help="top cell (default: the top cell)")
    ap.add_argument("--name", dest="ports", action="append", default=[], type=parse_port,
                    metavar="NAME=CONDUCTOR@X,Y",
                    help="name the body on CONDUCTOR touching point X,Y (µm); repeatable")
    add_flow_args(ap)
    args = ap.parse_args(argv)
    setup_logging(args.verbose)

    layout, top = load_gds(args.input, args.cell)
    from layz import stack as stackfile
    stack = stack_from_process(stackfile.load(args.stack), gds=True)
    run_flow(args, layout, top, stack, args.out or Path(f"run_{args.input.stem}"), args.ports)


if __name__ == "__main__":
    main()
