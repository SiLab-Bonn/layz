#!/usr/bin/env bash
# Install layz with Python's own venv and pip, and put the `layz` command on PATH for good.
# Run from the repo root (bash or zsh, Linux or macOS):
#
#     ./install.sh               install, or update after a pull (safe to re-run)
#     ./install.sh --uninstall   remove the `layz` link (keeps .venv/)
#
# It makes .venv/ with the Python that KiCad's pcbnew module is built for (Linux: python3;
# macOS: KiCad's own Python). Where python3 is older than 3.12 (3.9 on AlmaLinux 9) it takes the
# newest python3.15..3.12 installed, or else installs the newest the package manager offers (dnf,
# apt; asks for sudo). LAYZ_PYTHON=/path/to/python3 picks one yourself. It installs layz into the
# venv editable (changes in this repo apply directly) and links .venv/bin/layz where this terminal
# finds it (install/onpath.sh).
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
. "$here/install/onpath.sh"

if [ "${1:-}" = "--uninstall" ]; then
    for link in "$(onpath_dir)/layz" "$HOME/.local/bin/layz"; do
        [ -L "$link" ] && rm "$link" && echo "removed $link"
    done
    exit 0
fi

# --- the Python: KiCad's pcbnew only works with the Python it was built for (python3 on Linux,
# KiCad's own on macOS); where python3 is older than 3.12, the newest Python the system has, or
# else the newest its package manager offers (installed with sudo)
python="${LAYZ_PYTHON:-}"
mac_kicad=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
VERSIONS="3.15 3.14 3.13 3.12"   # layz's, newest first
pyversion() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }
supported() { case " $VERSIONS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
newest_installed() {
    for v in $VERSIONS; do
        cand="$(PATH="$PATH:$HOME/.local/bin" command -v "python$v" || true)"
        if [ -n "$cand" ] && supported "$(pyversion "$cand")"; then echo "$cand"; return; fi
    done
}
install_newest() {   # the newest python3.X package the package manager offers, with venv and pip
    for v in $VERSIONS; do
        if command -v dnf >/dev/null && dnf list --available -q "python$v" >/dev/null 2>&1; then
            cmd="as_root dnf install -y python$v python$v-pip"
        elif command -v apt-get >/dev/null && apt-cache show "python$v-venv" >/dev/null 2>&1; then
            cmd="as_root apt-get install -y python$v python$v-venv"
        else
            continue
        fi
        echo "layz: installing Python $v: $cmd"
        $cmd >&2 || { echo "layz: that failed; run it yourself (or ask an admin), then ./install.sh again" >&2; exit 1; }
        return
    done
}
if [ -z "$python" ]; then
    if [ "$(uname)" = "Darwin" ] && [ -x "$mac_kicad" ]; then
        python="$mac_kicad"
    else
        python="$(command -v python3 || true)"
        if [ -z "$python" ] || ! supported "$(pyversion "$python")"; then
            if [ -n "$python" ]; then old="python3 is Python $(pyversion "$python")"; else old="no python3"; fi
            python="$(newest_installed)"
            if [ -z "$python" ]; then
                install_newest
                python="$(newest_installed)"
            fi
            [ -n "$python" ] && echo "layz: $old; using $python (Python $(pyversion "$python"))"
        fi
    fi
fi
if [ -z "$python" ] || [ ! -x "$python" ]; then
    echo "layz: no Python $(echo $VERSIONS | tr ' ' '/') found or installable; install one, or set LAYZ_PYTHON=/path/to/python3" >&2
    exit 1
fi
version="$(pyversion "$python")"
if ! supported "$version"; then
    echo "layz: $python is Python $version; layz needs $(echo $VERSIONS | tr ' ' '/') (or set LAYZ_PYTHON=/path/to/python3)" >&2
    exit 1
fi
"$python" -c 'import pcbnew' 2>/dev/null \
    || echo "layz: note: $python can't import KiCad's pcbnew; layz looks for it at run time too (layz doctor)"

# --- venv + pip: a .venv from another Python (an earlier install with an older python3) is rebuilt
if [ -x "$here/.venv/bin/python" ] && [ "$(pyversion "$here/.venv/bin/python")" != "$version" ]; then
    echo "layz: $here/.venv is Python $(pyversion "$here/.venv/bin/python"); making it again with Python $version"
    rm -rf "$here/.venv"
fi
if [ ! -x "$here/.venv/bin/python" ]; then
    echo "layz: making $here/.venv with $python (Python $version)"
    "$python" -m venv --system-site-packages "$here/.venv"
fi
"$here/.venv/bin/python" -m pip install --quiet --upgrade pip
echo "layz: pip install --editable $here"
"$here/.venv/bin/python" -m pip install --quiet --editable "$here"

# --- on PATH: where this terminal finds it already (install/onpath.sh)
onpath_link "$here/.venv/bin/layz" layz
onpath_done
[ -z "$ONPATH_MISSING" ] && echo "layz: ready, try: layz doctor"
exit 0
