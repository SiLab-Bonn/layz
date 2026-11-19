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
REPO=$(cd "$(dirname "$0")/.." && pwd)
. "$REPO/install/onpath.sh"   # as_root, onpath_link

# --- prerequisites: installed if missing (otherwise they surface as CMake errors deep in the build);
# only what is missing, so e.g. AlmaLinux's curl-minimal stays
check() {
  missing=()
  for tool in cmake git curl make; do
    command -v "$tool" >/dev/null || missing+=("$tool")
  done
  command -v c++ >/dev/null || command -v g++ >/dev/null || command -v clang++ >/dev/null || missing+=("c++")
  if [[ "$(uname)" == Linux ]]; then
    command -v bzip2 >/dev/null || missing+=("bzip2")   # the wxWidgets source is a .tar.bz2
    # BLAS with its C header (cblas.h), which FasterCap's LinAlgebra needs
    local h found=
    for h in /usr/include/cblas.h /usr/include/*/cblas.h /usr/include/*/*/cblas.h \
             /usr/local/include/cblas.h /usr/local/include/*/cblas.h; do
      [[ -e "$h" ]] && { found=1; break; }
    done
    [[ -n "$found" ]] || missing+=("cblas")
  fi
}
# the package of each missing piece: package(manager, piece)
package() {
  case "$1:$2" in
    apt:c++) echo g++ ;; apt:cblas) echo libopenblas-dev ;;
    dnf:c++) echo gcc-c++ ;; dnf:cblas) echo openblas-devel ;;
    pacman:c++) echo gcc ;; pacman:cblas) echo openblas ;;
    *) echo "$2" ;;
  esac
}
check
if (( ${#missing[@]} )); then
  echo "build_solvers.sh: missing ${missing[*]}; installing" >&2
  if command -v apt-get >/dev/null; then pm=apt
  elif command -v dnf >/dev/null; then pm=dnf
  elif command -v pacman >/dev/null; then pm=pacman
  elif [[ "$(uname)" == Darwin ]] && command -v brew >/dev/null; then pm=brew
  else
    echo "build_solvers.sh: no known package manager; install ${missing[*]} yourself" >&2
    exit 1
  fi
  pkgs=()
  for m in "${missing[@]}"; do pkgs+=("$(package $pm "$m")"); done
  case $pm in
    apt) cmd=(as_root apt-get install -y "${pkgs[@]}") ;;
    dnf)
      # RHEL, AlmaLinux, Rocky: openblas-devel is in the CodeReady Builder repository (crb), off by default
      if [[ " ${pkgs[*]} " == *" openblas-devel "* ]] && ! dnf list -q openblas-devel >/dev/null 2>&1 && dnf repolist --all -q 2>/dev/null | grep -q "^crb "; then
        echo "+ as_root dnf config-manager --set-enabled crb" >&2
        as_root dnf install -y dnf-plugins-core >/dev/null && as_root dnf config-manager --set-enabled crb
      fi
      cmd=(as_root dnf install -y "${pkgs[@]}") ;;
    pacman) cmd=(as_root pacman -S --needed --noconfirm "${pkgs[@]}") ;;
    brew)
      xcode-select -p >/dev/null 2>&1 || xcode-select --install
      cmd=(brew install cmake libomp wxwidgets) ;;
  esac
  echo "+ ${cmd[*]}" >&2
  "${cmd[@]}" || { echo "build_solvers.sh: that failed; run it yourself (or ask an admin), then again" >&2; exit 1; }
  check
  (( ${#missing[@]} == 0 )) || { echo "build_solvers.sh: still missing ${missing[*]}" >&2; exit 1; }
fi

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
  ${WX_CONFIG:+-DwxWidgets_CONFIG_EXECUTABLE=$WX_CONFIG}
cmake --build build -j"$JOBS"
popd

# --- FastCap2 (optional, `layz pex --solver fastcap2`): its CMake needs GoogleTest, installed if
# the system's own repositories have it (RHEL and AlmaLinux keep it in EPEL: then FastCap2 is left out)
have_gtest() { compgen -G "/usr/include/gtest/gtest.h" >/dev/null || compgen -G "/usr/local/include/gtest/gtest.h" >/dev/null || compgen -G "/opt/homebrew/include/gtest/gtest.h" >/dev/null; }
if ! have_gtest; then
  case "${pm:-}" in
    "") if command -v apt-get >/dev/null; then pm=apt; elif command -v dnf >/dev/null; then pm=dnf; elif command -v pacman >/dev/null; then pm=pacman; elif command -v brew >/dev/null; then pm=brew; fi ;;
  esac
  case "${pm:-}" in
    apt) as_root apt-get install -y libgtest-dev || true ;;
    dnf) dnf list -q gtest-devel >/dev/null 2>&1 && as_root dnf install -y gtest-devel || true ;;
    pacman) as_root pacman -S --needed --noconfirm gtest || true ;;
    brew) brew install googletest || true ;;
  esac
fi
fastcap2=
if have_gtest; then
  [[ -d FastCap2 ]] || git clone -q https://github.com/martinjankoehler/FastCap2
  cmake -S FastCap2 -B FastCap2/build -DCMAKE_BUILD_TYPE=Release
  cmake --build FastCap2/build -j"$JOBS"
  fastcap2=1
else
  echo "build_solvers.sh: FastCap2 left out: it needs GoogleTest (gtest-devel), which this system's repositories don't have (on RHEL/AlmaLinux it is in EPEL); FasterCap, layz's default solver, is built" >&2
fi

onpath_link "$TOOLS/src/FastFieldSolvers/build/FasterCap" FasterCap
[[ -n "$fastcap2" ]] && onpath_link "$TOOLS/src/FastCap2/build/fastcap" fastcap
onpath_done
echo "check with: layz doctor"
