#!/usr/bin/env bash
# layz itself, for yourself, without sudo: a venv in the repo (.layz-env/, never activated: the
# `layz` command runs from it) on python3, or where that is older than 3.12 the newest Python the
# system has, layz installed in it editable (changes in this repo apply directly), and the `layz`
# command linked where this terminal finds it. KiCad's pcbnew is not needed here: layz runs those
# steps in its own KiCad (install/kicad.sh). No arguments; ./install.sh runs it.
# LAYZ_PYTHON=/path/to/python3 picks the Python yourself.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
. "$here/lib.sh"

python="$(find_python)" || need_system "Python 3.12 or newer (or set LAYZ_PYTHON=/path/to/python3)"
version="$(pyversion "$python")"
has_venv "$python" || need_system "Python $version's venv module (python$version-venv)"

# an environment from another Python (an earlier install with an older python3) is made again
if [ -x "$LAYZ_ENV/bin/python" ] && [ "$(pyversion "$LAYZ_ENV/bin/python")" != "$version" ]; then
    echo "layz: $LAYZ_ENV is Python $(pyversion "$LAYZ_ENV/bin/python"); making it again with Python $version"
    rm -rf "$LAYZ_ENV"
fi
if [ ! -x "$LAYZ_ENV/bin/python" ]; then
    echo "layz: making $LAYZ_ENV with $python (Python $version)"
    "$python" -m venv --system-site-packages "$LAYZ_ENV"
fi
# the package was src/ before 7825024: a pull leaves that folder with only Python's caches in it
if [ -d "$repo/src" ] && [ -z "$(find "$repo/src" -type f ! -path '*/__pycache__/*' -print -quit)" ]; then
    rm -rf "$repo/src"
fi
"$LAYZ_ENV/bin/python" -m pip install --quiet --upgrade pip
echo "layz: pip install --editable $repo"
# pip's output (setuptools' notes on editable installs) only if it fails
out="$("$LAYZ_ENV/bin/python" -m pip install --quiet --editable "$repo" 2>&1)" || { echo "$out" >&2; exit 1; }

onpath_link "$LAYZ_ENV/bin/layz" layz
onpath_done
