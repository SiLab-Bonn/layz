# Set up layz without uv, and put the `layz` command on PATH for this shell:
#
#     source workspace.sh
#
# The first time, it makes .venv/ with the system Python (the one KiCad's pcbnew module is built
# for; its packages stay visible) and installs layz into it with pip, editable, so changes in
# this repo take effect directly. Later runs only activate it. Override the Python with
# LAYZ_PYTHON=/path/to/python3 (macOS: KiCad's own, see README).
#
# With uv, `uv tool install --editable . --python /usr/bin/python3` does the same once, for good.

if [ -n "${BASH_SOURCE[0]:-}" ]; then _layz_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [ -n "${ZSH_VERSION:-}" ]; then _layz_here="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else _layz_here="$(pwd)"; fi

_layz_python="${LAYZ_PYTHON:-}"
if [ -z "$_layz_python" ]; then
    if [ "$(uname)" = "Darwin" ] && [ -x /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 ]; then
        _layz_python=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
    else
        _layz_python="$(command -v python3)"
    fi
fi

if [ ! -x "$_layz_here/.venv/bin/layz" ]; then
    echo "layz: making $_layz_here/.venv with $_layz_python"
    "$_layz_python" -m venv --system-site-packages "$_layz_here/.venv" &&
    "$_layz_here/.venv/bin/python" -m pip install --quiet --upgrade pip &&
    "$_layz_here/.venv/bin/python" -m pip install --quiet --editable "$_layz_here" ||
    { echo "layz: setup failed (see above)"; unset _layz_here _layz_python; return 1 2>/dev/null || exit 1; }
fi

case ":$PATH:" in
    *":$_layz_here/.venv/bin:"*) ;;
    *) export PATH="$_layz_here/.venv/bin:$PATH" ;;
esac
echo "layz: $(command -v layz) ready; run \`layz doctor\` to check the external tools"
unset _layz_here _layz_python
