#!/usr/bin/env bash
# Install gdscheck (https://github.com/aesc-silicon/gdscheck), the DRC engine of `layz drc`:
# Rust's cargo first if it's missing (apt, dnf, pacman with sudo; Homebrew on macOS), then
# `cargo install`, linked where this terminal finds it (install/onpath.sh). Run again to update.
set -euo pipefail

export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v cargo >/dev/null; then
  echo "install_gdscheck.sh: no cargo; installing Rust" >&2
  if command -v apt-get >/dev/null; then
    cmd=(sudo apt-get install -y cargo git)
  elif command -v dnf >/dev/null; then
    cmd=(sudo dnf install -y cargo git)
  elif command -v pacman >/dev/null; then
    cmd=(sudo pacman -S --needed --noconfirm rust git)
  elif command -v brew >/dev/null; then
    cmd=(brew install rust)
  else
    echo "install_gdscheck.sh: no known package manager; install Rust: https://www.rust-lang.org/tools/install" >&2
    exit 1
  fi
  echo "+ ${cmd[*]}" >&2
  "${cmd[@]}" || { echo "install_gdscheck.sh: that failed; run it yourself (or ask an admin), then again" >&2; exit 1; }
fi

cargo install --git https://github.com/aesc-silicon/gdscheck gdscheck
. "$(cd "$(dirname "$0")" && pwd)/onpath.sh"
onpath_link "$(command -v gdscheck)" gdscheck
onpath_done
echo "check with: layz doctor"
