#!/usr/bin/env bash
# Install layz and every tool it uses, for yourself, without sudo. Run from the repo:
#
#     ./install.sh               install, or update after a pull (safe to re-run)
#     ./install.sh --uninstall   remove the `layz` command (keeps .layz-env/)
#
# First it checks every system package any part needs, and if some are missing it lists them all
# and stops before installing anything: an admin installs them once for every user with
#     sudo install/system.sh
# Then, into your home and this repo: layz itself (install/layz.sh), layz's own KiCad 10
# (install/kicad.sh), FasterCap (install/fastercap.sh), gdscheck (install/gdscheck.sh), ParaView
# (install/paraview.sh), and `layz doctor` with layz's tests. Each step also runs on its own.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/install/lib.sh"

if [ "${1:-}" = "--uninstall" ]; then
    for link in "$(onpath_dir)/layz" "$HOME/.local/bin/layz"; do
        [ -L "$link" ] && rm "$link" && echo "removed $link"
    done
    exit 0
fi

echo "=== system packages"
missing="$(system_missing)"
if [ -n "$missing" ]; then
    echo "missing:"
    echo "$missing" | sed 's/^/    /'
    need_system "the system packages above"
fi
echo "all there"

step() {
    echo
    echo "=== $1"
    "$here/install/$1"
}
step layz.sh
step kicad.sh
step fastercap.sh
step gdscheck.sh
step paraview.sh

echo
echo "=== layz doctor"
"$LAYZ_ENV/bin/layz" doctor || echo "(layz doctor reports something missing above)"
onpath_done
