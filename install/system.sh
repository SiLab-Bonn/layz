#!/usr/bin/env bash
# The system packages of layz and its tools, for every user of a machine. No arguments.
#
#   sudo install/system.sh     Linux: once per machine, by an admin (asks for sudo itself if needed)
#   install/system.sh          macOS: Homebrew, as yourself
#
# It is the only one of layz's installers that needs root. Afterwards each user runs ./install.sh,
# without sudo: it checks that these packages are there, then installs the rest into their home.
#
#   Python 3.12+ with venv    for layz (the newest the system has, where python3 is older)
#   cmake, a C++ compiler, make, git, curl, bzip2, BLAS headers   to build FasterCap
#   GoogleTest, Python headers   to build FastCap2 too (optional; where GoogleTest is packaged)
#   cargo (Rust)              to build gdscheck
#   KiCad 10                  macOS only (Homebrew's cask); on Linux each user's install/kicad.sh
#                             unpacks KiCad's AppImage, apart from any system KiCad
#   KLayout                   klayout.org's build (Ubuntu, RHEL, macOS), else the distribution's
#   ParaView                  where the system packages it
#
# Run it again after a system upgrade; it only adds what is missing.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/lib.sh"

family="$(os_family)"
if [ "$family" != macos ] && [ "$(id -u)" != 0 ]; then
    echo "system.sh installs system packages: running it with sudo"
    exec sudo "$0" "$@"
fi
[ "$family" = macos ] && [ "$(id -u)" = 0 ] && die "on macOS run it as yourself (Homebrew refuses root)"

mac_install_dmg() {   # copy the .app of a .dmg into /Applications
    local mnt
    mnt="$(mktemp -d)"
    hdiutil attach -nobrowse -quiet -mountpoint "$mnt" "$1" 2>/dev/null || return 1   # (its deprecation notice)
    for app in "$mnt"/*.app; do
        rm -rf "/Applications/$(basename "$app")"   # replaced, not merged into an older version
        cp -R "$app" /Applications/ || { hdiutil detach -quiet "$mnt"; return 1; }
    done
    hdiutil detach -quiet "$mnt"
}

done_list=()
skipped=()
group() {   # group WHAT PKG...: install a group of packages; a failure skips the group, not the run
    local what="$1"
    shift
    echo "=== $what: $*"
    if pkg_install "$@"; then done_list+=("$what"); else skipped+=("$what (install failed: $*)"); fi
}
skip() { skipped+=("$1"); echo "=== $1"; }

# KLayout from klayout.org where it builds for this system (newer than the distributions'), the
# same version as layz's klayout Python module
KLAYOUT=0.30.13
klayout_official() {   # klayout_official URL INSTALLER...: download the package, install it with INSTALLER
    local url="$1" tmp
    shift
    tmp="$(mktemp -d)"
    echo "=== KLayout $KLAYOUT: $url"
    if curl -fsSL -o "$tmp/$(basename "$url")" "$url" && "$@" "$tmp/$(basename "$url")"; then
        done_list+=("KLayout $KLAYOUT")
    else
        skipped+=("KLayout $KLAYOUT (from $url)")
    fi
    rm -rf "$tmp"
}

newest_python_pkg() {   # the newest python3.X (3.12..3.15) the package manager offers, if python3 is older
    local v
    for v in 3.15 3.14 3.13 3.12; do
        case "$1" in
            apt) apt-cache show "python$v-venv" >/dev/null 2>&1 && { echo "$v"; return; } ;;
            dnf) dnf list -q "python$v" >/dev/null 2>&1 && { echo "$v"; return; } ;;
        esac
    done
}
python3_ok() { python3 -c 'import sys; sys.exit(not (3, 12) <= sys.version_info[:2] <= (3, 15))' 2>/dev/null; }

case "$family" in
    ubuntu | debian)
        as_root apt-get update -q
        PKG_UPDATED=1
        if python3_ok; then
            v="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
            group "Python $v" python3 "python$v-venv" python3-pip
        elif v="$(newest_python_pkg apt)" && [ -n "$v" ]; then
            group "Python $v" "python$v" "python$v-venv"
        else
            skip "Python 3.12+: not packaged here (Ubuntu 22.04, Debian 12: python3 is older)"
        fi
        group "build tools" cmake g++ make git curl ca-certificates bzip2 libopenblas-dev
        group "FastCap2's build: GoogleTest, Python headers" libgtest-dev python3-dev
        group "Rust (gdscheck)" cargo
        group "ParaView" paraview
        if [ "$family" = ubuntu ]; then
            u="$(. /etc/os-release && echo "${VERSION_ID%%.*}")"
            klayout_official "https://www.klayout.org/downloads/Ubuntu-$u/klayout_${KLAYOUT}-1_amd64.deb" as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends
        else
            group "KLayout (Debian's; klayout.org builds none for Debian)" klayout
        fi
        ;;
    rhel)
        # openblas-devel and other build pieces are in the CodeReady Builder repository (crb)
        if dnf repolist --all -q 2>/dev/null | grep -q "^crb "; then
            pkg_install dnf-plugins-core >/dev/null && as_root dnf config-manager --set-enabled crb
        fi
        if python3_ok; then
            group "Python" python3-pip
        elif v="$(newest_python_pkg dnf)" && [ -n "$v" ]; then
            group "Python $v" "python$v" "python$v-pip"
        else
            skip "Python 3.12+: not packaged here"
        fi
        tools=(cmake gcc-c++ make git-core bzip2 openblas-devel)   # git-core: git without openssh
        command -v curl >/dev/null || tools+=(curl)   # curl-minimal provides it; the full curl would clash
        group "build tools" "${tools[@]}"
        if dnf list -q gtest-devel >/dev/null 2>&1; then group "FastCap2's build: GoogleTest, Python headers" gtest-devel python3-devel; else skip "FastCap2's GoogleTest: only in EPEL; FasterCap builds without it"; fi
        group "Rust (gdscheck)" cargo
        # each user's install/paraview.sh unpacks ParaView's own build (EPEL has only 5.11): its libraries
        libs=()
        for l in $PARAVIEW_LIBS; do libs+=("$l()(64bit)"); done
        group "libraries of ParaView's own build" "${libs[@]}"
        el="$(. /etc/os-release && echo "${VERSION_ID%%.*}")"
        case "$el" in
            9) klayout_official "https://www.klayout.org/downloads/RockyLinux_9/klayout-${KLAYOUT}-0.x86_64.rpm" as_root dnf install -y ;;
            8) klayout_official "https://www.klayout.org/downloads/CentOS_8/klayout-${KLAYOUT}-0.x86_64.rpm" as_root dnf install -y ;;
            *) skip "KLayout: klayout.org builds for RHEL 8 and 9 only" ;;
        esac
        ;;
    fedora)
        group "Python" python3 python3-pip
        group "build tools" cmake gcc-c++ make git bzip2 openblas-devel
        group "FastCap2's build: GoogleTest, Python headers" gtest-devel python3-devel
        group "Rust (gdscheck)" cargo
        group "ParaView" paraview
        group "KLayout" klayout
        ;;
    arch)
        group "Python" python python-pip
        group "build tools" cmake gcc make git curl bzip2 openblas
        group "FastCap2's build: GoogleTest" gtest
        group "Rust (gdscheck)" rust
        group "ParaView" paraview
        group "KLayout" klayout
        ;;
    macos)
        command -v brew >/dev/null || die "install Homebrew first: https://brew.sh"
        # Homebrew without its auto-update (pages of new packages), hints and progress bars
        export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 HOMEBREW_NO_INSTALL_CLEANUP=1
        xcode-select -p >/dev/null 2>&1 || xcode-select --install
        group "build tools" cmake libomp wxwidgets googletest
        group "Rust (gdscheck)" rust
        # KLayout: klayout.org's build for this macOS (the ST builds, on the system's Ruby and Python)
        mac="$(sw_vers -productVersion | cut -d. -f1)"
        case "$mac" in
            14) dmg="MacOS/ST-klayout-$KLAYOUT-macOS-Sonoma-C32-1-qt5MP-RsysPsys.dmg" ;;
            15) dmg="MacOS/ST-klayout-$KLAYOUT-macOS-Sequoia-C32-1-qt5MP-RsysPsys.dmg" ;;
            26) dmg="MacOS/ARM64/arm64ST-klayout-$KLAYOUT-macOS-Tahoe-C32-1-qt5MP-RsysPsys.dmg" ;;
            27) dmg="MacOS/ARM64/arm64ST-klayout-$KLAYOUT-macOS-GoldenGate-C32-1-qt5MP-RsysPsys.dmg" ;;
            *) dmg= ;;
        esac
        if [ -n "$dmg" ]; then
            klayout_official "https://www.klayout.org/downloads/$dmg" mac_install_dmg
        else
            skip "KLayout: klayout.org has no build for macOS $mac; https://www.klayout.de/build.html"
        fi
        # an app already in /Applications (installed by hand, say) counts: Homebrew won't install over it
        for c in "kicad:/Applications/KiCad/KiCad.app" "paraview:/Applications/ParaView*.app"; do
            name="${c%%:*}"
            if ls -d ${c#*:} >/dev/null 2>&1; then
                done_list+=("$name (in /Applications already)")
            elif brew install --quiet --cask "$name"; then
                done_list+=("$name")
            else
                skipped+=("$name (brew install --cask $name failed)")
            fi
        done
        ;;
    *)
        die "not a system this script knows (Debian, Ubuntu, AlmaLinux/RHEL, Fedora, Arch, macOS)"
        ;;
esac

echo
echo "installed or already there: ${done_list[*]:-nothing}"
for s in "${skipped[@]}"; do echo "not here: $s"; done
echo "each user now runs, without sudo, from the layz folder: ./install.sh"
