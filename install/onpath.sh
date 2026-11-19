# Sourced by layz's installers (install.sh, install/build_solvers.sh, install/install_gdscheck.sh):
# put a command where the running shell finds it, so it works without opening a new terminal.
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
