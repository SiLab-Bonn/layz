#!/usr/bin/env bash
# ParaView with pvpython, for `layz view` of field results. No arguments, no sudo.
#
#   Debian, Ubuntu, Fedora, Arch, macOS   a system package (install/system.sh); this checks it
#                                         and, on macOS, links pvpython onto your PATH
#   AlmaLinux, Rocky, RHEL                ParaView's own Linux build (EPEL has only 5.11),
#                                         unpacked into ~/.local/share/layz/paraview-<version>
#
# Run again to update.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

VERSION=6.2.1   # ParaView's own build, for RHEL-like systems
SERIES=6.2
TOOLS=${TOOLS:-${XDG_DATA_HOME:-$HOME/.local/share}/layz}

case "$(os_family)" in
    rhel)
        [ "$(uname -m)" = x86_64 ] || die "ParaView's Linux build is for x86_64; this is $(uname -m)"
        command -v curl >/dev/null || need_system curl
        name="ParaView-$VERSION-MPI-Linux-Python3.12-x86_64"
        dest="$TOOLS/paraview-$VERSION"
        if [ ! -x "$dest/bin/pvpython" ]; then
            mkdir -p "$TOOLS"
            rm -rf "$TOOLS/paraview-unpack"
            mkdir "$TOOLS/paraview-unpack"
            echo "downloading $name.tar.gz (about 870 MB) from paraview.org"
            curl -fsSL "https://www.paraview.org/files/v$SERIES/$name.tar.gz" | tar xz --no-same-owner -C "$TOOLS/paraview-unpack"
            rm -rf "$dest"
            mv "$TOOLS/paraview-unpack/$name" "$dest"
            rmdir "$TOOLS/paraview-unpack"
        fi
        onpath_link "$dest/bin/pvpython" pvpython
        onpath_link "$dest/bin/paraview" paraview
        onpath_done
        ;;
    macos)
        app="$(ls -d /Applications/ParaView*.app 2>/dev/null | sort -V | tail -1)"
        [ -n "$app" ] || need_system "ParaView (Homebrew's paraview cask)"
        onpath_link "$app/Contents/bin/pvpython" pvpython
        onpath_done
        ;;
    *)
        command -v pvpython >/dev/null || need_system "ParaView (pvpython)"
        ;;
esac

pv="$(command -v pvpython || echo "$(onpath_dir)/pvpython")"
"$pv" --version 2>/dev/null | head -1 || die "pvpython does not run: $pv"
echo "check with: layz doctor"
