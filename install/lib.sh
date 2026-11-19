# Sourced by layz's installers (install.sh and install/*.sh):
#
#   os_family                 debian, ubuntu, rhel (AlmaLinux, Rocky, RHEL, CentOS), fedora, arch,
#                             macos, or unknown
#   need_system WHAT...       stop: these system packages are missing, install/system.sh adds them
#   system_missing            every system package layz's install needs that is missing, one per
#                             line (./install.sh checks them all before installing anything)
#   find_python, pyversion, has_venv, find_cblas, kicad_packaged   the checks it uses
#   pkg_install PKG...        install packages with the system's package manager (install/system.sh)
#   as_root CMD...            run a command as root (sudo unless we are root)
#   die MESSAGE               print it and exit 1
#
# and put a command where the running shell finds it, so it works without opening a new terminal:
#
#   onpath_link TARGET NAME   link TARGET as NAME into onpath_dir
#   onpath_done               after the links: "ready", or the one line to run if none could be
#
# onpath_dir is a folder of your own that is already on PATH: ~/.local/bin or ~/bin, else the
# first writable one under $HOME. Only if there is none, ~/.local/bin is used and added to PATH
# in ~/.bashrc / ~/.zshrc for new terminals.

# run a command as root: directly when we are root, else through sudo (which asks for a password)
as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi
}

die() {
    echo "$(basename "$0"): $*" >&2
    exit 1
}

# --- the checks of the system packages (install/system.sh installs them)

PY_VERSIONS="3.15 3.14 3.13 3.12"   # layz's, newest first
# layz's own Python environment, in the repo; nobody activates it (the `layz` command runs from it).
# Not .venv: that is the name a user's own `python -m venv` would take, and overwrite.
LAYZ_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.layz-env"
MAC_KICAD_PYTHON=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3

pyversion() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }
py_supported() { case " $PY_VERSIONS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
has_venv() { "$1" -c 'import ensurepip, venv' 2>/dev/null; }

# the Python for layz: $LAYZ_PYTHON; on macOS KiCad's; python3 if it is 3.12+; else the newest
# python3.15..3.12 there is
find_python() {
    local p v
    if [ -n "${LAYZ_PYTHON:-}" ]; then echo "$LAYZ_PYTHON"; return; fi
    if [ "$(uname)" = Darwin ] && [ -x "$MAC_KICAD_PYTHON" ]; then echo "$MAC_KICAD_PYTHON"; return; fi
    p="$(command -v python3 || true)"
    if [ -n "$p" ] && py_supported "$(pyversion "$p")"; then echo "$p"; return; fi
    for v in $PY_VERSIONS; do
        p="$(command -v "python$v" || true)"
        if [ -n "$p" ] && py_supported "$(pyversion "$p")"; then echo "$p"; return; fi
    done
    return 1
}

# the folder with cblas.h (FasterCap's LinAlgebra looks in the standard path and openblas/ only;
# fastercap.sh names it, e.g. FlexiBLAS's /usr/include/flexiblas on AlmaLinux 9)
find_cblas() {
    local d
    for d in /usr/include /usr/include/openblas /usr/include/flexiblas /usr/include/x86_64-linux-gnu \
             /usr/include/aarch64-linux-gnu /usr/include/blis /usr/local/include /usr/local/include/openblas; do
        [ -e "$d/cblas.h" ] && { echo "$d"; return; }
    done
    return 1
}

# the shared libraries ParaView's own Linux build needs (paraview.sh, on RHEL-like systems), which a
# desktop has and a minimal install may not; system.sh installs them by name
PARAVIEW_LIBS="libEGL.so.1 libGL.so.1 libGLX.so.0 libOpenGL.so.0 libX11.so.6 libX11-xcb.so.1 libfontconfig.so.1 libpciaccess.so.0 libxcb.so.1 libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-image.so.0 libxcb-keysyms.so.1 libxcb-randr.so.0 libxcb-render.so.0 libxcb-render-util.so.0 libxcb-shape.so.0 libxcb-shm.so.0 libxcb-sync.so.1 libxcb-xfixes.so.0 libxcb-xkb.so.1 libxkbcommon.so.0 libxkbcommon-x11.so.0"
paraview_libs_missing() {
    local l have
    have="$(/sbin/ldconfig -p 2>/dev/null || ldconfig -p 2>/dev/null)"
    for l in $PARAVIEW_LIBS; do
        echo "$have" | grep -q "^[[:space:]]*$l " || echo "$l"
    done
}

# whether this system has a KiCad 10 package (AlmaLinux/RHEL and Debian 13 don't)
kicad_packaged() {
    local k
    case "$(os_family)" in
        ubuntu | arch | macos) return 0 ;;
        debian) k="$(apt-cache policy kicad 2>/dev/null | sed -n 's/^ *Candidate: \([0-9]*\)\..*/\1/p')"; [ "${k:-0}" -ge 10 ] ;;
        fedora) k="$(dnf info -q kicad 2>/dev/null | sed -n 's/^Version *: \([0-9]*\)\..*/\1/p' | sort -n | tail -1)"; [ "${k:-0}" -ge 10 ] ;;
        *) return 1 ;;
    esac
}

system_missing() {
    local fam p t
    fam="$(os_family)"
    if p="$(find_python)"; then
        has_venv "$p" || echo "Python $(pyversion "$p")'s venv module"
    else
        echo "Python 3.12 or newer"
    fi
    for t in cmake make git curl; do command -v "$t" >/dev/null || echo "$t"; done
    command -v c++ >/dev/null || command -v g++ >/dev/null || command -v clang++ >/dev/null || echo "a C++ compiler"
    if [ "$fam" = macos ]; then
        command -v brew >/dev/null && [ -d "$(brew --prefix)/opt/libomp" ] || echo "libomp (Homebrew)"
    else
        command -v bzip2 >/dev/null || echo "bzip2"
        find_cblas >/dev/null || echo "BLAS headers (cblas.h)"
    fi
    command -v cargo >/dev/null || [ -x "${CARGO_HOME:-$HOME/.cargo}/bin/cargo" ] || echo "Rust's cargo"
    if kicad_packaged; then
        if [ "$fam" = macos ]; then [ -d /Applications/KiCad/KiCad.app ] || echo "KiCad 10"; else command -v kicad-cli >/dev/null || echo "KiCad 10"; fi
    fi
    case "$fam" in
        rhel) [ -z "$(paraview_libs_missing)" ] || echo "the libraries of ParaView's own build ($(paraview_libs_missing | tr '\n' ' '))" ;;
        macos) ls -d /Applications/ParaView*.app >/dev/null 2>&1 || echo "ParaView" ;;
        *) command -v pvpython >/dev/null || echo "ParaView (pvpython)" ;;
    esac
    case "$fam" in
        rhel) ;;   # no package: https://www.klayout.de/build.html
        macos) [ -d /Applications/klayout.app ] || [ -d /Applications/KLayout/klayout.app ] || echo "KLayout" ;;
        *) command -v klayout >/dev/null || echo "KLayout" ;;
    esac
}

# the per-user scripts don't install system packages: install/system.sh does, once per machine
need_system() {
    local how="sudo install/system.sh"
    [ "$(os_family)" = macos ] && how="install/system.sh"
    die "missing $*: these are system packages, installed once for every user with
    $how
(from the layz folder; on Linux an admin runs it), then run this again"
}

os_family() {
    if [ "$(uname)" = Darwin ]; then echo macos; return; fi
    local id="" like=""
    if [ -r /etc/os-release ]; then
        id="$(. /etc/os-release && echo "${ID:-}")"
        like="$(. /etc/os-release && echo "${ID_LIKE:-}")"
    fi
    case " $id $like " in
        *" ubuntu "*) echo ubuntu ;;
        *" debian "*) echo debian ;;
        *" fedora "*) if [ "$id" = fedora ]; then echo fedora; else echo rhel; fi ;;
        *" rhel "* | *" centos "*) echo rhel ;;
        *" arch "*) echo arch ;;
        *) echo unknown ;;
    esac
}

PKG_UPDATED=
pkg_install() {
    case "$(os_family)" in
        ubuntu | debian)
            [ -n "$PKG_UPDATED" ] || { as_root apt-get update -q && PKG_UPDATED=1; }
            # without recommended extras: only what is asked for (e.g. git without an ssh client)
            as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@" ;;
        rhel | fedora) as_root dnf install -y "$@" ;;
        arch) as_root pacman -S --needed --noconfirm "$@" ;;
        macos)
            command -v brew >/dev/null || die "install Homebrew first (https://brew.sh), then run this again"
            brew install "$@" ;;
        *) die "no known package manager here; install $* yourself" ;;
    esac
}

onpath_dir() {
    local d
    for d in "$HOME/.local/bin" "$HOME/bin"; do
        case ":$PATH:" in *":$d:"*) [ -d "$d" ] && [ -w "$d" ] && { echo "$d"; return; } ;; esac
    done
    local IFS=:
    for d in $PATH; do
        case "$d" in "$HOME"/*) [ -d "$d" ] && [ -w "$d" ] && { echo "$d"; return; } ;; esac
    done
    echo "$HOME/.local/bin"
}

ONPATH_MISSING=
onpath_link() {
    local dir
    dir="$(onpath_dir)"
    mkdir -p "$dir"
    if [ "$(readlink -f "$1")" = "$(readlink -f "$dir/$2" 2>/dev/null)" ] && [ "$(cd "$(dirname "$1")" && pwd -P)" = "$(cd "$dir" && pwd -P)" ]; then
        echo "$2 is in $dir already"   # the command lives in a folder on PATH itself
    else
        ln -sf "$1" "$dir/$2"
        echo "linked $dir/$2 -> $1"
    fi
    case ":$PATH:" in
        *":$dir:"*) ;;
        *)
            ONPATH_MISSING="$dir"
            local rc line="export PATH=\"$dir:\$PATH\""
            case "${SHELL:-}" in */zsh) rc="$HOME/.zshrc" ;; *) rc="$HOME/.bashrc" ;; esac
            if ! grep -qsF "$line" "$rc"; then
                printf '\n# added by layz\n%s\n' "$line" >> "$rc"
                echo "added $dir to PATH in $rc (for new terminals)"
            fi
            ;;
    esac
}

onpath_done() {   # the one line to run in this terminal, if the folder of the links isn't on PATH
    local dir
    dir="$(onpath_dir)"
    case ":$PATH:" in
        *":$dir:"*) ;;
        *) echo "in this terminal, run once: export PATH=\"$dir:\$PATH\"" ;;
    esac
}
