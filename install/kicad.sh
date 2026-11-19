#!/usr/bin/env bash
# layz's own KiCad 10, kept apart from any KiCad you have: no arguments, no sudo, nothing on PATH.
#
#   Linux (x86_64)  KiCad's AppImage, unpacked into ~/.local/share/layz/kicad-<version>
#   macOS           KiCad.app (install/system.sh installs it with Homebrew)
#
# plus ~/.local/share/layz/kicad-env: a Python environment on KiCad's own Python (3.11 in the
# AppImage), where layz runs the steps that need KiCad's pcbnew module (gds2hyp from a board or
# GDS, reading a board for pex); layz.kicad finds both. Run again to update.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

VERSION=10.0.8
TOOLS=${TOOLS:-${XDG_DATA_HOME:-$HOME/.local/share}/layz}
ENV="$TOOLS/kicad-env"
# what the KiCad steps import (the rest of layz runs in .layz-env)
PACKAGES=("klayout>=0.30.12" "shapely>=2.0" numpy "kicad-pycbnew==1.0.1" pyyaml)

case "$(os_family)" in
    macos)
        app=/Applications/KiCad/KiCad.app
        [ -d "$app" ] || need_system "KiCad 10 (Homebrew's kicad cask)"
        cli="$app/Contents/MacOS/kicad-cli"
        py="$app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
        ;;
    *)
        [ "$(uname -m)" = x86_64 ] || die "KiCad's AppImage is for x86_64; this is $(uname -m)"
        command -v curl >/dev/null || need_system curl
        dest="$TOOLS/kicad-$VERSION"
        if [ ! -x "$dest/bin/kicad-cli" ]; then
            mkdir -p "$TOOLS"
            app="$TOOLS/kicad-$VERSION-x86_64-lite.AppImage"   # kept: a re-run doesn't download again
            if [ ! -s "$app" ]; then
                echo "downloading KiCad $VERSION's AppImage (about 300 MB) from KiCad's mirror"
                curl -fsSL "https://mirrors.mit.edu/kicad/appimage/stable/kicad-$VERSION-x86_64-lite.AppImage.tar" | tar x -O > "$app.part"
                mv "$app.part" "$app"
                chmod +x "$app"
            fi
            work="$TOOLS/kicad-unpack"
            rm -rf "$work" "$dest"
            mkdir "$work"
            (cd "$work" && "$app" --appimage-extract >/dev/null)   # unpacked: no FUSE needed
            mv "$(readlink -f "$work/squashfs-root")" "$dest"      # squashfs-root links to the real folder
            rm -rf "$work"
        fi
        cli="$dest/bin/kicad-cli"
        py="$(ls "$dest"/bin/python3.* | head -1)"
        ;;
esac

# the KiCad environment, on KiCad's Python; made again when it was made from another one
if [ ! -x "$ENV/bin/python" ] || [ "$(cat "$ENV/.kicad-python" 2>/dev/null)" != "$py" ]; then
    rm -rf "$ENV"
    echo "making $ENV on KiCad's Python ($("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])'))"
    "$py" -m venv "$ENV"
    echo "$py" > "$ENV/.kicad-python"
fi
"$ENV/bin/python" -m pip install --quiet --upgrade pip
"$ENV/bin/python" -m pip install --quiet "${PACKAGES[@]}"

v="$("$ENV/bin/python" -c 'import pcbnew; print(pcbnew.Version())')" || die "KiCad's pcbnew doesn't import in $ENV"
echo "KiCad $("$cli" --version): kicad-cli and pcbnew ($v) in $TOOLS"
