#!/usr/bin/env bash
# Install gdscheck (https://github.com/aesc-silicon/gdscheck), the DRC engine of layz.drc, for
# yourself, without sudo: `cargo install` into ~/.cargo, linked where this terminal finds it. No
# arguments. Needs Rust's cargo (install/system.sh). Run again to update.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

bin="${CARGO_HOME:-$HOME/.cargo}/bin"   # where cargo install puts it (and rustup's cargo)
cargo="$(command -v cargo || true)"
[ -z "$cargo" ] && [ -x "$bin/cargo" ] && cargo="$bin/cargo"
[ -n "$cargo" ] || need_system "Rust's cargo"
command -v git >/dev/null || need_system git

PATH="$bin:$PATH" "$cargo" install --git https://github.com/aesc-silicon/gdscheck gdscheck   # with its bin on PATH: no warning about it
onpath_link "$bin/gdscheck" gdscheck
onpath_done
echo "check with: layz doctor"
