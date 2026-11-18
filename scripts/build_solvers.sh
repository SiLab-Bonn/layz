#!/usr/bin/env bash
# Build the field solvers used by `layz pex` into $TOOLS (default: ~/.local/share/layz) and link
# them into ~/.local/bin, where layz finds them on PATH (or set LAYZ_FASTERCAP / LAYZ_FASTCAP2).
# The Python side is the repo's own venv (README: python3 -m venv ... && pip install).
#
#   tools/src/FastFieldSolvers/build/FasterCap   iic-jku/FasterCap, headless   (LGPL-2.1)
#   tools/src/FastCap2/build/fastcap       martinjankoehler/FastCap2           (MIT license)
#   tools/wx                               wxWidgets 3.2.6 "base" (non-GUI) library, for FasterCap
#
# Debian/Ubuntu/Kali prerequisites: sudo apt install cmake g++ make git curl libopenblas-dev
#   (checked below, with the matching command for Fedora, Arch and macOS)
#   (wxWidgets is built here because Ubuntu 26.04 ships no wx headers without the GTK dev stack;
#    `sudo apt install wx3.2-headers libwxgtk3.2-dev` and dropping the wx step works as well)
# macOS: brew install cmake libomp wxwidgets; export OpenMP_ROOT=$(brew --prefix)/opt/libomp
#   then skip the wx step (Homebrew's wx-config is found), or use the arm64 release tarball from
#   https://github.com/iic-jku/FasterCap/releases and set FASTERCAP to its executable.
set -euo pipefail

# --- prerequisites, checked up front (otherwise they surface as CMake errors deep in the build)
missing=()
for tool in cmake git curl make; do
  command -v "$tool" >/dev/null || missing+=("$tool")
done
command -v c++ >/dev/null || command -v g++ >/dev/null || command -v clang++ >/dev/null || missing+=("a C++ compiler")
if [[ "$(uname)" == Linux ]]; then
  # BLAS with its C header (cblas.h), which FasterCap's LinAlgebra needs: libopenblas-dev
  found_cblas=
  for h in /usr/include/cblas.h /usr/include/*/cblas.h /usr/include/*/*/cblas.h \
           /usr/local/include/cblas.h /usr/local/include/*/cblas.h; do
    [[ -e "$h" ]] && { found_cblas=1; break; }
  done
  [[ -n "$found_cblas" ]] || missing+=("BLAS headers (cblas.h)")
fi
if (( ${#missing[@]} )); then
  echo "build_solvers.sh: missing: ${missing[*]}" >&2
  if command -v apt-get >/dev/null; then
    echo "  Debian, Ubuntu, Kali: sudo apt install cmake g++ make git curl libopenblas-dev" >&2
  elif command -v dnf >/dev/null; then
    echo "  Fedora: sudo dnf install cmake gcc-c++ make git curl openblas-devel" >&2
  elif command -v pacman >/dev/null; then
    echo "  Arch: sudo pacman -S cmake gcc make git curl openblas" >&2
  elif [[ "$(uname)" == Darwin ]]; then
    echo "  macOS: xcode-select --install; brew install cmake libomp wxwidgets" >&2
  fi
  exit 1
fi

REPO=$(cd "$(dirname "$0")/.." && pwd)
TOOLS=${TOOLS:-${XDG_DATA_HOME:-$HOME/.local/share}/layz}
JOBS=${JOBS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu)}
mkdir -p "$TOOLS/src"
cd "$TOOLS/src"

# --- wxWidgets base (Linux only)
WX_CONFIG=$(command -v wx-config || true)
if [[ -z "$WX_CONFIG" && "$(uname)" == Linux ]]; then
  [[ -d wxWidgets-3.2.6 ]] || curl -sSL https://github.com/wxWidgets/wxWidgets/releases/download/v3.2.6/wxWidgets-3.2.6.tar.bz2 | tar xj
  mkdir -p wxWidgets-3.2.6/build-base && pushd wxWidgets-3.2.6/build-base
  ../configure --prefix="$TOOLS/wx" --disable-gui --enable-unicode --disable-tests --without-subdirs
  make -j"$JOBS" && make install
  popd
  WX_CONFIG=$TOOLS/wx/bin/wx-config
fi

# --- FasterCap (needs LinAlgebra and Geometry next to it)
mkdir -p FastFieldSolvers && pushd FastFieldSolvers
for r in FasterCap LinAlgebra Geometry; do
  [[ -d $r ]] || git clone -q "https://github.com/iic-jku/$r.git"
done
cmake -S FasterCap -B build -DCMAKE_BUILD_TYPE=Release -DFASTFIELDSOLVERS_HEADLESS=ON \
  ${WX_CONFIG:+-DwxWidgets_CONFIG_EXECUTABLE=$WX_CONFIG}
cmake --build build -j"$JOBS"
popd

# --- FastCap2
[[ -d FastCap2 ]] || git clone -q https://github.com/martinjankoehler/FastCap2
cmake -S FastCap2 -B FastCap2/build -DCMAKE_BUILD_TYPE=Release
cmake --build FastCap2/build -j"$JOBS"

mkdir -p "$HOME/.local/bin"
ln -sf "$TOOLS/src/FastFieldSolvers/build/FasterCap" "$HOME/.local/bin/FasterCap"
ln -sf "$TOOLS/src/FastCap2/build/fastcap" "$HOME/.local/bin/fastcap"
echo
echo "FasterCap: $TOOLS/src/FastFieldSolvers/build/FasterCap -> ~/.local/bin/FasterCap"
echo "FastCap2:  $TOOLS/src/FastCap2/build/fastcap -> ~/.local/bin/fastcap"
echo "check with: layz doctor"
