#!/usr/bin/env bash
# Install gdscheck (https://github.com/aesc-silicon/gdscheck), the DRC engine of `layz drc`:
# Rust's cargo first if it's missing (apt, dnf, pacman with sudo; Homebrew on macOS), then
# `cargo install`, linked where this terminal finds it (install/lib.sh). Run again to update.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"   # as_root, onpath_link

bin="${CARGO_HOME:-$HOME/.cargo}/bin"   # where cargo install puts it (and rustup's cargo)
cargo="$(command -v cargo || true)"
[ -z "$cargo" ] && [ -x "$bin/cargo" ] && cargo="$bin/cargo"
if [ -z "$cargo" ]; then
  echo "gdscheck.sh: no cargo; installing Rust" >&2
  if command -v apt-get >/dev/null; then
    cmd=(as_root apt-get install -y cargo git)
  elif command -v dnf >/dev/null; then
    cmd=(as_root dnf install -y cargo git)
  elif command -v pacman >/dev/null; then
    cmd=(as_root pacman -S --needed --noconfirm rust git)
  elif command -v brew >/dev/null; then
    cmd=(brew install rust)
  else
    echo "gdscheck.sh: no known package manager; install Rust: https://www.rust-lang.org/tools/install" >&2
    exit 1
  fi
  echo "+ ${cmd[*]}" >&2
  "${cmd[@]}" || { echo "gdscheck.sh: that failed; run it yourself (or ask an admin), then again" >&2; exit 1; }
  cargo="$(command -v cargo)"
fi

"$cargo" install --git https://github.com/aesc-silicon/gdscheck gdscheck
onpath_link "$bin/gdscheck" gdscheck
onpath_done
echo "check with: layz doctor"
