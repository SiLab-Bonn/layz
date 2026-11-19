#!/usr/bin/env bash
# Install layz with Python's own venv and pip, and put the `layz` command on PATH for good.
# Run from the repo root (bash or zsh, Linux or macOS):
#
#     ./install.sh               install, or update after a pull (safe to re-run)
#     ./install.sh --uninstall   remove the `layz` link (keeps .venv/)
#
# It makes .venv/ with the Python that KiCad's pcbnew module is built for (Linux: python3;
# macOS: KiCad's own Python); where python3 is older than 3.12 (e.g. 3.9 on AlmaLinux 9) it takes
# the newest of python3.14, python3.13, python3.12 on PATH or in ~/.local/bin instead. It installs layz into it editable (changes in this repo apply
# directly), and links .venv/bin/layz where this terminal finds it (install/onpath.sh). Override the Python with LAYZ_PYTHON=/path/to/python3.
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
. "$here/install/onpath.sh"

if [ "${1:-}" = "--uninstall" ]; then
    for link in "$(onpath_dir)/layz" "$HOME/.local/bin/layz"; do
        [ -L "$link" ] && rm "$link" && echo "removed $link"
    done
    exit 0
fi

# --- the Python: KiCad's pcbnew only works with the Python it was built for
python="${LAYZ_PYTHON:-}"
mac_kicad=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
pyversion() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }
supported() { case "$1" in 3.12|3.13|3.14|3.15) return 0 ;; *) return 1 ;; esac; }
if [ -z "$python" ]; then
    if [ "$(uname)" = "Darwin" ] && [ -x "$mac_kicad" ]; then python="$mac_kicad"
    else
        python="$(command -v python3 || true)"
        # python3 too old (3.9, 3.10, ...): the newest python3.14..3.12 there is
        if [ -z "$python" ] || ! supported "$(pyversion "$python")"; then
            old="$python"
            for v in 3.14 3.13 3.12; do
                cand="$(PATH="$PATH:$HOME/.local/bin" command -v "python$v" || true)"
                if [ -n "$cand" ] && supported "$(pyversion "$cand")"; then python="$cand"; break; fi
            done
            if [ "$python" != "$old" ]; then
                if [ -n "$old" ]; then why="Python $(pyversion "$old"), too old"; else why="missing"; fi
                echo "layz: python3 is $why; using $python"
            fi
        fi
    fi
fi
if [ -z "$python" ] || [ ! -x "$python" ]; then
    echo "layz: no python3 found; set LAYZ_PYTHON=/path/to/python3" >&2; exit 1
fi
version="$(pyversion "$python")"
if ! supported "$version"; then
    echo "layz: $python is Python $version and no python3.14, 3.13 or 3.12 was found; layz needs" \
         "3.12 to 3.15 (install one, or set LAYZ_PYTHON=/path/to/python3)" >&2
    exit 1
fi
"$python" -c 'import pcbnew' 2>/dev/null \
    || echo "layz: note: $python can't import KiCad's pcbnew; layz looks for it at run time too (layz doctor)"

# --- venv + pip
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
