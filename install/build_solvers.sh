#!/usr/bin/env bash
# Build the field solvers used by `layz pex` into $TOOLS (default: ~/.local/share/layz) and link
# them where this terminal finds them (install/onpath.sh).
#
#   tools/src/FastFieldSolvers/build/FasterCap   iic-jku/FasterCap, headless   (LGPL-2.1)
#   tools/src/FastCap2/build/fastcap       martinjankoehler/FastCap2           (MIT license)
#   tools/wx                               wxWidgets 3.2.6 "base" (non-GUI) library, for FasterCap
#
# Installs its build tools first with the system's package manager (apt, dnf, pacman; asks for
# sudo), or with Homebrew on macOS. wxWidgets is built here (Ubuntu ships no wx headers without the
# GTK dev stack). macOS also needs: export OpenMP_ROOT=$(brew --prefix)/opt/libomp
set -euo pipefail

# --- prerequisites: installed if missing (otherwise they surface as CMake errors deep in the build)
check() {
  missing=()
  for tool in cmake git curl make; do
    command -v "$tool" >/dev/null || missing+=("$tool")
  done
  command -v c++ >/dev/null || command -v g++ >/dev/null || command -v clang++ >/dev/null || missing+=("a C++ compiler")
  if [[ "$(uname)" == Linux ]]; then
    # BLAS with its C header (cblas.h), which FasterCap's LinAlgebra needs
    local h found=
    for h in /usr/include/cblas.h /usr/include/*/cblas.h /usr/include/*/*/cblas.h \
             /usr/local/include/cblas.h /usr/local/include/*/cblas.h; do
      [[ -e "$h" ]] && { found=1; break; }
    done
    [[ -n "$found" ]] || missing+=("BLAS headers (cblas.h)")
  fi
}
check
if (( ${#missing[@]} )); then
  echo "build_solvers.sh: missing ${missing[*]}; installing" >&2
  if command -v apt-get >/dev/null; then
    cmd=(sudo apt-get install -y cmake g++ make git curl libopenblas-dev)
  elif command -v dnf >/dev/null; then
    cmd=(sudo dnf install -y cmake gcc-c++ make git curl openblas-devel)
  elif command -v pacman >/dev/null; then
    cmd=(sudo pacman -S --needed --noconfirm cmake gcc make git curl openblas)
  elif [[ "$(uname)" == Darwin ]] && command -v brew >/dev/null; then
    xcode-select -p >/dev/null 2>&1 || xcode-select --install
    cmd=(brew install cmake libomp wxwidgets)
  else
    echo "build_solvers.sh: no known package manager; install ${missing[*]} yourself" >&2
    exit 1
  fi
  echo "+ ${cmd[*]}" >&2
  "${cmd[@]}" || { echo "build_solvers.sh: that failed; run it yourself (or ask an admin), then again" >&2; exit 1; }
  check
  (( ${#missing[@]} == 0 )) || { echo "build_solvers.sh: still missing ${missing[*]}" >&2; exit 1; }
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

. "$REPO/install/onpath.sh"
onpath_link "$TOOLS/src/FastFieldSolvers/build/FasterCap" FasterCap
onpath_link "$TOOLS/src/FastCap2/build/fastcap" fastcap
onpath_done
echo "check with: layz doctor"
