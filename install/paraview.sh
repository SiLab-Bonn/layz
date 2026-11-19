#!/usr/bin/env bash
# Install ParaView with pvpython, for `layz view` of field results. No arguments.
#
#   Debian, Ubuntu, Fedora, Arch   the distribution's paraview package
#   AlmaLinux, Rocky, RHEL         ParaView's own Linux build (EPEL's is 5.11), unpacked into
#                                  ~/.local/share/layz/paraview-<version>
#   macOS                          Homebrew's paraview cask
#
# pvpython ends up where this terminal finds it (install/lib.sh). Run again to update.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

VERSION=6.2.1   # ParaView's own build, for RHEL-like systems
SERIES=6.2
TOOLS=${TOOLS:-${XDG_DATA_HOME:-$HOME/.local/share}/layz}

case "$(os_family)" in
    ubuntu | debian | fedora | arch)
        pkg_install paraview
        ;;
    rhel)
        [ "$(uname -m)" = x86_64 ] || die "ParaView's Linux build is for x86_64; this is $(uname -m)"
        name="ParaView-$VERSION-MPI-Linux-Python3.12-x86_64"
        dest="$TOOLS/paraview-$VERSION"
        if [ ! -x "$dest/bin/pvpython" ]; then
            command -v curl >/dev/null || pkg_install curl
            mkdir -p "$TOOLS"
            rm -rf "$TOOLS/paraview-unpack"
            mkdir "$TOOLS/paraview-unpack"
            echo "downloading $name.tar.gz (about 870 MB) from paraview.org"
            curl -fSL "https://www.paraview.org/files/v$SERIES/$name.tar.gz" | tar xz --no-same-owner -C "$TOOLS/paraview-unpack"
            rm -rf "$dest"
            mv "$TOOLS/paraview-unpack/$name" "$dest"
            rmdir "$TOOLS/paraview-unpack"
        fi
        onpath_link "$dest/bin/pvpython" pvpython
        onpath_link "$dest/bin/paraview" paraview
        ;;
    macos)
        command -v brew >/dev/null || die "install Homebrew first (https://brew.sh), or ParaView from https://www.paraview.org/download/"
        brew install --cask paraview
        app="$(ls -d /Applications/ParaView*.app | sort -V | tail -1)"
        onpath_link "$app/Contents/bin/pvpython" pvpython
        ;;
    *)
        die "not a system this script knows; get ParaView from https://www.paraview.org/download/"
        ;;
esac
onpath_done

pv="$(command -v pvpython || echo "$(onpath_dir)/pvpython")"
"$pv" --version 2>/dev/null | head -1 || die "pvpython does not run: $pv"
echo "check with: layz doctor"
