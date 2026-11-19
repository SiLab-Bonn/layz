# Sourced by layz's installers (install.sh and install/*.sh):
#
#   os_family                 debian, ubuntu, rhel (AlmaLinux, Rocky, RHEL, CentOS), fedora, arch,
#                             macos, or unknown
#   pkg_install PKG...        install packages with the system's package manager (as root)
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
            as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
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

onpath_done() {
    if [ -n "$ONPATH_MISSING" ]; then
        echo "in this terminal, run once: export PATH=\"$ONPATH_MISSING:\$PATH\""
    fi
}
