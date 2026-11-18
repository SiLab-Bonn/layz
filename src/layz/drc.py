"""`layz drc`: design rule check of a GDS with gdscheck and the kit's rule deck.

    layz drc --lay design.gds --kit uni-bonn-rdl [-o design.lyrdb] [--suite main|geometry]
    layz drc --lay design.gds --kit uni-bonn-rdl --benchmark   # time each rule
    layz view design.lyrdb --lay design.gds          # KLayout with the violation markers

Decks are gdscheck PDKs in the repo's drc/<kit>/ (pdk.yml, decks/, suites/), in gdscheck's own
format. Exit status: 0 clean, 2 violations (gdscheck's), 1 errors.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DRC_DIR = Path(__file__).resolve().parents[2] / "drc"


def kits() -> list[str]:
    return sorted(p.parent.name for p in DRC_DIR.glob("*/pdk.yml"))


def top_cell(gds: Path) -> str:
    import klayout.db as db
    layout = db.Layout()
    layout.read(str(gds))
    tops = layout.top_cells()
    if len(tops) != 1:
        raise SystemExit(f"{gds}: {len(tops)} top cells ({', '.join(c.name for c in tops)}); "
                         "pick one with --topcell")
    return tops[0].name


def suite_rules(kit: str, suite: str) -> list[tuple[str, str]]:
    """(deck, rule id) of every rule a suite runs, in order."""
    import yaml
    base = DRC_DIR / kit
    pdk = yaml.safe_load((base / "pdk.yml").read_text())
    decks = {d["name"]: base / d["path"] for d in pdk.get("decks", [])}
    suites = {x["name"]: base / x["path"] for x in pdk.get("suites", [])}
    out = []
    for inc in yaml.safe_load(suites[suite].read_text()).get("include", []):
        rules = [r["id"] for r in yaml.safe_load(decks[inc["deck"]].read_text()).get("rules", [])]
        keep = inc.get("rules")
        drop = set(inc.get("exclude", []))
        out += [(inc["deck"], r) for r in rules if (keep is None or r in keep) and r not in drop]
    return out


def benchmark(gdscheck: str, args, top: str) -> int:
    """Run each rule of the suite on its own and print the times, slowest first. A one-rule
    suite per rule in a temporary copy of the kit's deck (gdscheck has no per-rule timing)."""
    import tempfile
    import time
    import yaml
    rules = suite_rules(args.kit, args.suite)
    with tempfile.TemporaryDirectory() as tmp:
        kit_dir = Path(tmp) / args.kit
        shutil.copytree(DRC_DIR / args.kit, kit_dir)
        pdk = yaml.safe_load((kit_dir / "pdk.yml").read_text())
        for n, (deck, rule) in enumerate(rules):
            (kit_dir / "suites" / f"_p{n}.yml").write_text(
                yaml.safe_dump({"include": [{"deck": deck, "rules": [rule]}]}))
            pdk["suites"].append({"name": f"_p{n}", "path": f"suites/_p{n}.yml", "description": rule})
        (kit_dir / "pdk.yml").write_text(yaml.safe_dump(pdk, sort_keys=False))
        rows = []
        print(f"benchmarking {len(rules)} rules of {args.kit}/{args.suite} on {args.lay} "
              f"(tile {args.tile:g} µm) ...", flush=True)
        for n, (deck, rule) in enumerate(rules):
            t0 = time.perf_counter()
            r = subprocess.run([gdscheck, "run", "--pdk-path", tmp, "-p", args.kit, "-s", f"_p{n}",
                                "-t", top, "--tile", str(args.tile), "-i", str(args.lay)],
                               capture_output=True, text=True)
            dt = time.perf_counter() - t0
            found = next((l.split()[0] for l in r.stdout.splitlines() if l.endswith("violation(s):")), "0")
            rows.append((dt, rule, deck, found))
            print(f"  {rule:<24} {dt:8.2f} s  {found:>6} violations", flush=True)
    total = sum(r[0] for r in rows)
    print(f"\nslowest first (total {total:.1f} s, each run includes reading the layout):")
    for dt, rule, deck, found in sorted(rows, reverse=True)[:10]:
        print(f"  {rule:<24} {deck:<10} {dt:8.2f} s  {100 * dt / total:5.1f} %")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lay", type=Path, required=True, help="layout (.gds, .gds.gz)")
    ap.add_argument("--kit", required=True, help=f"process kit: {', '.join(kits()) or '(none found)'}")
    ap.add_argument("-o", "--out", type=Path, help="report (.lyrdb; default: next to the layout)")
    ap.add_argument("--suite", default="main", help="gdscheck suite (default: main)")
    ap.add_argument("--topcell", help="top cell (default: the layout's only top cell)")
    ap.add_argument("--tile", type=float, default=20000.0,
                    help="gdscheck merge tile, µm (default 20000: board/RDL scale, ~5x faster than "
                         "2 mm on the obelix1 ladder; gdscheck's own 20 µm is for chips)")
    ap.add_argument("--benchmark", action="store_true",
                    help="time each rule on its own (slowest first) instead of one combined run; "
                         "no report is written")
    ap.add_argument("-v", "--verbose", action="store_true", help="every violation's message")
    args = ap.parse_args(argv)

    from layz import solvers
    gdscheck = solvers.find("gdscheck")
    if args.kit not in kits():
        raise SystemExit(f"no DRC deck for kit {args.kit!r}; have: {', '.join(kits())}")
    top = args.topcell or top_cell(args.lay)
    if args.benchmark:
        return benchmark(gdscheck, args, top)
    out = args.out or args.lay.with_suffix(".lyrdb")
    cmd = [gdscheck, "run", "--pdk-path", str(DRC_DIR), "-p", args.kit, "-s", args.suite,
           "-t", top, "--tile", str(args.tile), "-i", str(args.lay), "-r", str(out)]
    if args.verbose:
        cmd.append("-v")
    rc = subprocess.call(cmd)
    if out.exists():
        print(f"open in KLayout: layz view {out} --lay {args.lay}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
