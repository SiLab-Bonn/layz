"""Find a HyperLynx install, build the writable overlay layz runs it from, and its environment.

Install: $LAYZ_HYPERLYNX_HOME (the SDD_HOME folder, which holds hyperlynx/ and Scripting/), else
the newest /eda/Siemens/*/RHELx86/HLVX_*/*/SDD_HOME or /opt/*/HLVX*/*/SDD_HOME.

Overlay: $LAYZ_HYPERLYNX_OVERLAY, else ~/.local/share/layz/hyperlynx/<release>/SDD_HOME. Every
entry of SDD_HOME is a symlink to the install, except hyperlynx/, a real folder of symlinks
with writable copies of the files HyperLynx writes (Bsw.pak, ...). HyperLynx's Python finds
its program folder from where it is started, so it runs as <overlay>/Scripting/bin/pythonHL.

License: $MGLS_LICENSE_FILE (port@server), or $LAYZ_HYPERLYNX_LICENSE for the same value, else
SiLab's server (DEFAULT_LICENSE): nothing needs setting in the shell on SiLab's machines.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
from pathlib import Path

WRITABLE = ("Bsw.pak", "Bsw.alg", "Bsw.fbd", "Bsw.mask")  # opened read-write by BoardSim
ARCH = "amd64_linux"
SEARCH = ("/eda/Siemens/*/RHELx86/HLVX_*/*/SDD_HOME", "/eda/Siemens/*/RHELx86/HLVX_*/SDD_HOME", "/opt/*/HLVX*/*/SDD_HOME", "/opt/*/HLVX*/SDD_HOME")


def find_install() -> Path:
    env = os.environ.get("LAYZ_HYPERLYNX_HOME")
    if env:
        p = Path(env)
        if not (p / "Scripting" / "bin" / "pythonHL").exists():
            raise SystemExit(f"LAYZ_HYPERLYNX_HOME={env} has no Scripting/bin/pythonHL (point it at SDD_HOME)")
        return p
    hits = sorted({Path(h) for pat in SEARCH for h in glob.glob(pat) if (Path(h) / "Scripting" / "bin" / "pythonHL").exists()})
    if not hits:
        raise SystemExit("HyperLynx not found: set LAYZ_HYPERLYNX_HOME to its SDD_HOME folder (the one holding hyperlynx/ and Scripting/)")
    return hits[-1]  # newest release by path (2024-25/... sorts after 2023-24/...)


def overlay_dir(install: Path) -> Path:
    env = os.environ.get("LAYZ_HYPERLYNX_OVERLAY")
    if env:
        return Path(env)
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    release = install.parent.name or "hyperlynx"
    return data / "layz" / "hyperlynx" / release / "SDD_HOME"


def ensure_overlay(install: Path, overlay: Path, quiet: bool = False) -> Path:
    """Build (or refresh) the overlay of ``install`` at ``overlay``; returns it."""
    stamp = overlay / ".layz-overlay"
    if stamp.exists() and stamp.read_text().strip() == str(install):
        return overlay
    if overlay.exists() and not stamp.exists() and any(overlay.iterdir()):
        raise SystemExit(f"{overlay} exists and is not a layz overlay: remove it or set LAYZ_HYPERLYNX_OVERLAY")
    overlay.mkdir(parents=True, exist_ok=True)
    for entry in install.iterdir():
        dst = overlay / entry.name
        if entry.name == "hyperlynx":
            continue
        if dst.is_symlink() or dst.exists():
            if dst.is_symlink():
                dst.unlink()
            else:
                continue
        dst.symlink_to(entry)
    hl_src, hl_dst = install / "hyperlynx", overlay / "hyperlynx"
    if hl_dst.is_symlink():
        hl_dst.unlink()
    hl_dst.mkdir(exist_ok=True)
    for entry in hl_src.iterdir():
        dst = hl_dst / entry.name
        if entry.name in WRITABLE:
            if not dst.exists() or dst.is_symlink():
                if dst.is_symlink():
                    dst.unlink()
                shutil.copy2(entry, dst)
                dst.chmod(0o644)
            continue
        if dst.is_symlink():
            dst.unlink()
        if not dst.exists():
            dst.symlink_to(entry)
    stamp.write_text(f"{install}\n")
    if not quiet:
        print(f"HyperLynx overlay: {overlay} (of {install})", file=sys.stderr)
    return overlay


DEFAULT_LICENSE = "27504@nexus.physik.uni-bonn.de"  # SiLab's Siemens license server


def license_value() -> str:
    return os.environ.get("MGLS_LICENSE_FILE") or os.environ.get("LAYZ_HYPERLYNX_LICENSE") or DEFAULT_LICENSE


def environment(install: Path, overlay: Path) -> dict[str, str]:
    """The environment HyperLynx's setup script makes, pointed at the overlay."""
    lic = license_value()
    env = dict(os.environ)
    common = install / "common" / ARCH
    hl = overlay / "hyperlynx"
    env.update({"MGC_HLVX": str(install.parent), "MG_HLVX_ARCH": ARCH, "MWHOME": str(common / "MainWin5"), "MGLS_HOME": str(common / "mgls"), "HYP_HOME": f"{hl}/", "HLAS_HOME": str(install / "Nimbic" / "bin"), "HLD_HOME": str(install / "hldrc" / "linux64" / "bin"), "MW64BIT": "1", "MGLS_LICENSE_FILE": lic, "SALT_LICENSE_SERVER": os.environ.get("SALT_LICENSE_SERVER", lic), "PYTHONUNBUFFERED": "1"})
    env["PATH"] = os.pathsep.join([str(hl), str(install / "Nimbic" / "bin"), str(install / "hldrc" / "linux64" / "bin"), str(common / "bin"), env.get("PATH", "")])
    env["LD_LIBRARY_PATH"] = os.pathsep.join([str(common / "lib"), str(install / "hldrc" / "linux64" / "bin"), env.get("LD_LIBRARY_PATH", "")]).rstrip(os.pathsep)
    return env


def python(overlay: Path) -> Path:
    return overlay / "Scripting" / "bin" / "pythonHL"


def prepare(quiet: bool = False) -> tuple[Path, Path, dict[str, str]]:
    install = find_install()
    overlay = ensure_overlay(install, overlay_dir(install), quiet=quiet)
    return install, overlay, environment(install, overlay)
