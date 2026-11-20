#!/usr/bin/env bash
# Build the field solvers used by layz.pex into $TOOLS (default: ~/.local/share/layz) and link
# them where this terminal finds them (install/lib.sh).
#
#   tools/src/FastFieldSolvers/build/FasterCap   iic-jku/FasterCap, headless   (LGPL-2.1)
#   tools/src/FastCap2/build/fastcap       martinjankoehler/FastCap2           (MIT license)
#   tools/wx                               wxWidgets 3.2.6 "base" (non-GUI) library, for FasterCap
#
# For yourself, without sudo; no arguments. Its build tools are system packages (install/system.sh):
# it checks for them and stops naming what is missing. wxWidgets is built here (Ubuntu ships no wx
# headers without the GTK dev stack). Run again to update.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
. "$REPO/install/lib.sh"   # need_system, onpath_link

# --- prerequisites: system packages (install/system.sh); a missing one would surface as a CMake
# error deep in the build
missing=()
for tool in cmake git curl make; do
  command -v "$tool" >/dev/null || missing+=("$tool")
done
command -v c++ >/dev/null || command -v g++ >/dev/null || command -v clang++ >/dev/null || missing+=("a C++ compiler")
CBLAS_DIR=
if [[ "$(uname)" == Linux ]]; then
  command -v bzip2 >/dev/null || missing+=("bzip2")   # the wxWidgets source is a .tar.bz2
  CBLAS_DIR="$(find_cblas)" || missing+=("BLAS headers (cblas.h)")   # its folder goes to FasterCap's build
fi
(( ${#missing[@]} == 0 )) || need_system "${missing[*]}"
[[ "$(uname)" == Darwin ]] && export OpenMP_ROOT="${OpenMP_ROOT:-$(brew --prefix)/opt/libomp}"

TOOLS=${TOOLS:-${XDG_DATA_HOME:-$HOME/.local/share}/layz}
JOBS=${JOBS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu)}
mkdir -p "$TOOLS/src"
cd "$TOOLS/src"

# --- wxWidgets base (Linux only)
WX_CONFIG=$(command -v wx-config || true)
if [[ -z "$WX_CONFIG" && "$(uname)" == Linux ]]; then
  if [[ ! -d wxWidgets-3.2.6 ]]; then  # unpacked aside first: an interrupted unpack isn't taken for a whole one
    rm -rf wx-unpack && mkdir wx-unpack
    curl -sSL https://github.com/wxWidgets/wxWidgets/releases/download/v3.2.6/wxWidgets-3.2.6.tar.bz2 | tar xj --no-same-owner -C wx-unpack
    mv wx-unpack/wxWidgets-3.2.6 . && rmdir wx-unpack
  fi
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
  ${WX_CONFIG:+-DwxWidgets_CONFIG_EXECUTABLE=$WX_CONFIG} ${CBLAS_DIR:+-DCBLAS_INCLUDE_DIR=$CBLAS_DIR}
cmake --build build -j"$JOBS"
popd

# --- FastCap2 (optional, layz.pex with solver="fastcap2"): its CMake needs GoogleTest and the Python
# headers, system packages where the system has them (install/system.sh; on RHEL and AlmaLinux
# GoogleTest is only in EPEL)
have_gtest() {
  { compgen -G "/usr/include/gtest/gtest.h" || compgen -G "/usr/local/include/gtest/gtest.h" || compgen -G "/opt/homebrew/include/gtest/gtest.h"; } >/dev/null &&
    { [[ "$(uname)" == Darwin ]] || compgen -G "/usr/include/python3*/Python.h" >/dev/null; }
}
fastcap2=
if have_gtest; then
  [[ -d FastCap2 ]] || git clone -q https://github.com/martinjankoehler/FastCap2
  cmake -S FastCap2 -B FastCap2/build -DCMAKE_BUILD_TYPE=Release
  cmake --build FastCap2/build -j"$JOBS"
  fastcap2=1
else
  echo "fastercap.sh: FastCap2 left out: it needs GoogleTest and the Python headers, not both installed here (install/system.sh adds them where the system packages them); FasterCap, layz's default solver, is built" >&2
fi

onpath_link "$TOOLS/src/FastFieldSolvers/build/FasterCap" FasterCap
[[ -n "$fastcap2" ]] && onpath_link "$TOOLS/src/FastCap2/build/fastcap" fastcap
onpath_done
echo "check with: layz doctor"
