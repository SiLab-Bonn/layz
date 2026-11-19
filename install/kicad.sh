#!/usr/bin/env bash
# Install KiCad 10: kicad-cli and the pcbnew Python module that layz uses. No arguments.
#
#   Ubuntu        KiCad's PPA kicad-10.0-releases (22.04, 24.04, 26.04)
#   Debian        Debian's kicad where it is 10 (testing, unstable; Debian 13 has 9)
#   Fedora        Fedora's kicad where it is 10
#   macOS         Homebrew's kicad cask; layz then runs on KiCad's own Python: ./install.sh again
#   AlmaLinux, RHEL, Rocky, Debian 13 and older: no KiCad 10 package; see the message below
#
# Run again to update.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

major() { "$1" --version 2>/dev/null | sed -n 's/^\([0-9]*\)\..*/\1/p' | head -1; }

no_package() {
    die "no KiCad 10 package for this system ($1). KiCad offers an AppImage and a Flatpak for it
(https://www.kicad.org/download/linux/), but neither gives the system's Python the pcbnew
module layz needs, so this script doesn't install them yet. Until then, run layz's KiCad steps
(gds2pcb, gds2hyp from a GDS, pex on boards, lvs) on a machine with KiCad 10; the rest of layz
works without it."
}

case "$(os_family)" in
    ubuntu)
        command -v add-apt-repository >/dev/null || pkg_install software-properties-common
        as_root add-apt-repository -y ppa:kicad/kicad-10.0-releases
        PKG_UPDATED=
        pkg_install kicad
        ;;
    debian)
        as_root apt-get update -q
        PKG_UPDATED=1
        candidate="$(apt-cache policy kicad | sed -n 's/^ *Candidate: \([0-9]*\)\..*/\1/p')"
        [ "${candidate:-0}" -ge 10 ] || no_package "Debian's kicad is ${candidate:-missing} here"
        pkg_install kicad
        ;;
    fedora)
        candidate="$(dnf info -q kicad 2>/dev/null | sed -n 's/^Version *: \([0-9]*\)\..*/\1/p' | sort -n | tail -1)"
        [ "${candidate:-0}" -ge 10 ] || no_package "Fedora's kicad is ${candidate:-missing} here"
        pkg_install kicad
        ;;
    macos)
        command -v brew >/dev/null || die "install Homebrew first (https://brew.sh), or KiCad from https://www.kicad.org/download/macos/"
        brew install --cask kicad
        onpath_link /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli kicad-cli
        echo "layz uses KiCad's own Python on macOS: run ./install.sh again"
        ;;
    rhel)
        no_package "AlmaLinux, Rocky, RHEL"
        ;;
    *)
        no_package "unknown system"
        ;;
esac
onpath_done

cli="$(command -v kicad-cli || echo "$(onpath_dir)/kicad-cli")"
[ "$(major "$cli")" = 10 ] || die "kicad-cli is not KiCad 10: $("$cli" --version 2>&1 | head -1)"
echo "kicad-cli $("$cli" --version)"
echo "check with: layz doctor"
