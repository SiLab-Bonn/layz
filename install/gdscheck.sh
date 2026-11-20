#!/usr/bin/env bash
# Install gdscheck (https://github.com/aesc-silicon/gdscheck), the DRC engine of layz.drc, for
# yourself, without sudo: `cargo install` into ~/.cargo, linked where this terminal finds it. No
# arguments. Needs Rust's cargo (install/system.sh). Pinned to the commit layz's decks are checked
# with (REV): built once; a run again skips it while that one is installed. To update, change REV.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

REV=71f5752df46e590847a42d7a888ecb9123453985   # gdscheck 0.2.1, 2026-11-19
bin="${CARGO_HOME:-$HOME/.cargo}/bin"   # where cargo install puts it (and rustup's cargo)
cargo="$(command -v cargo || true)"
[ -z "$cargo" ] && [ -x "$bin/cargo" ] && cargo="$bin/cargo"
[ -n "$cargo" ] || need_system "Rust's cargo"
command -v git >/dev/null || need_system git

# cargo rebuilds a git install even when that commit is installed: skip it ourselves then
if [ -x "$bin/gdscheck" ] && grep -q "gdscheck?rev=$REV" "${CARGO_HOME:-$HOME/.cargo}/.crates.toml" 2>/dev/null; then
    echo "gdscheck ${REV:0:7} already installed"
else
    PATH="$bin:$PATH" "$cargo" install --force --git https://github.com/aesc-silicon/gdscheck --rev "$REV" gdscheck   # with its bin on PATH: no warning about it
fi
onpath_link "$bin/gdscheck" gdscheck
onpath_done
echo "check with: layz doctor"
