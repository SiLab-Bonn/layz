#!/usr/bin/env bash
# layz itself, for yourself, without sudo: a venv in the repo (.layz-env/, never activated: the `layz` command runs from it) with the Python that KiCad's
# pcbnew module is built for (python3 on Linux, KiCad's own on macOS; where python3 is older than
# 3.12, the newest Python the system has), layz installed in it editable (changes in this repo
# apply directly), and the `layz` command linked where this terminal finds it. No arguments;
# ./install.sh runs it. LAYZ_PYTHON=/path/to/python3 picks the Python yourself.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
. "$here/lib.sh"

python="$(find_python)" || need_system "Python 3.12 or newer (or set LAYZ_PYTHON=/path/to/python3)"
version="$(pyversion "$python")"
has_venv "$python" || need_system "Python $version's venv module (python$version-venv)"
"$python" -c 'import pcbnew' 2>/dev/null || echo "layz: note: $python can't import KiCad's pcbnew; layz looks for it at run time too (install/kicad.sh, layz doctor)"

# an environment from another Python (an earlier install with an older python3) is made again
if [ -x "$LAYZ_ENV/bin/python" ] && [ "$(pyversion "$LAYZ_ENV/bin/python")" != "$version" ]; then
    echo "layz: $LAYZ_ENV is Python $(pyversion "$LAYZ_ENV/bin/python"); making it again with Python $version"
    rm -rf "$LAYZ_ENV"
fi
if [ ! -x "$LAYZ_ENV/bin/python" ]; then
    echo "layz: making $LAYZ_ENV with $python (Python $version)"
    "$python" -m venv --system-site-packages "$LAYZ_ENV"
fi
"$LAYZ_ENV/bin/python" -m pip install --quiet --upgrade pip
echo "layz: pip install --editable $repo"
"$LAYZ_ENV/bin/python" -m pip install --quiet --editable "$repo"

onpath_link "$LAYZ_ENV/bin/layz" layz
onpath_done
