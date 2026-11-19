#!/usr/bin/env bash
# Check that KiCad 10 is there for layz: kicad-cli, and the pcbnew Python module. No arguments, no
# sudo: KiCad itself is a system package (install/system.sh: KiCad's PPA on Ubuntu, Debian
# testing, Fedora, Arch, Homebrew on macOS). On macOS it also links kicad-cli onto your PATH.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/lib.sh"

major() { "$1" --version 2>/dev/null | sed -n 's/^\([0-9]*\)\..*/\1/p' | head -1; }

case "$(os_family)" in
    rhel)
        die "KiCad 10 has no package for AlmaLinux/RHEL (KiCad offers only an AppImage and a Flatpak,
neither of which gives the system's Python the pcbnew module layz needs). Run layz's KiCad steps
(gds2pcb, gds2hyp from a GDS, pex on boards, lvs) on a machine with KiCad 10; the rest of layz
works without it."
        ;;
    macos)
        app=/Applications/KiCad/KiCad.app
        [ -d "$app" ] || need_system "KiCad 10 (Homebrew's kicad cask)"
        onpath_link "$app/Contents/MacOS/kicad-cli" kicad-cli
        onpath_done
        python="$app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
        ;;
    *)
        command -v kicad-cli >/dev/null || need_system "KiCad 10"
        python=python3
        ;;
esac

cli="$(command -v kicad-cli || echo "$(onpath_dir)/kicad-cli")"
[ "$(major "$cli")" = 10 ] || need_system "KiCad 10 (this kicad-cli is $("$cli" --version 2>&1 | head -1))"
"$python" -c "import pcbnew" 2>/dev/null || need_system "KiCad's pcbnew Python module (for $python)"
echo "KiCad $("$cli" --version): kicad-cli and pcbnew are there"
if ! "$LAYZ_ENV/bin/python" -c "import pcbnew" 2>/dev/null; then
    echo "layz's environment can't import pcbnew yet: run ./install.sh again (it then uses KiCad's Python)"
fi
echo "check with: layz doctor"
