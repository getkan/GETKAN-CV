#!/usr/bin/env bash
# Install the LaTeX toolchain required by GETKAN-CV on Linux and macOS.
set -euo pipefail

VERIFY_ONLY=0
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: scripts/install-latex.sh [options]

Options:
  --verify-only   Only check that the required tools and packages are present.
  --dry-run       Print the commands that would run without executing them.
  -h, --help      Show this help text.

Installs: xelatex, latexmk, fontspec, unicode-math, fontawesome5,
sourcesanspro, tcolorbox, enumitem, ragged2e, geometry, fancyhdr, xcolor,
xifthen, etoolbox, setspace, parskip, hyperref, plus poppler (pdfinfo) and
fontconfig.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --verify-only) VERIFY_ONLY=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

log() { printf '[install-latex] %s\n' "$*"; }
err() { printf '[install-latex] ERROR: %s\n' "$*" >&2; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    fi
fi

run() {
    log "run: $*"
    if [ "$DRY_RUN" -eq 1 ]; then
        return 0
    fi
    "$@"
}

detect_platform() {
    case "$(uname -s)" in
        Darwin) echo "macos"; return ;;
        Linux) : ;;
        *) echo "unsupported"; return ;;
    esac

    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        for id in ${ID:-} ${ID_LIKE:-}; do
            case "$id" in
                debian|ubuntu) echo "debian"; return ;;
                fedora|rhel|centos) echo "fedora"; return ;;
                arch) echo "arch"; return ;;
                opensuse*|suse) echo "suse"; return ;;
            esac
        done
    fi
    echo "unsupported"
}

install_debian() {
    run $SUDO apt-get update
    run $SUDO apt-get install -y \
        texlive-xetex \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-fonts-extra \
        latexmk \
        poppler-utils \
        fontconfig
}

install_fedora() {
    run $SUDO dnf install -y \
        texlive-xetex \
        texlive-collection-latexrecommended \
        texlive-collection-latexextra \
        texlive-collection-fontsrecommended \
        texlive-collection-fontsextra \
        texlive-latexmk \
        poppler-utils \
        fontconfig
}

install_arch() {
    run $SUDO pacman -S --needed --noconfirm \
        texlive-xetex \
        texlive-latexrecommended \
        texlive-latexextra \
        texlive-fontsrecommended \
        texlive-fontsextra \
        texlive-binextra \
        poppler \
        fontconfig
}

install_suse() {
    run $SUDO zypper install -y \
        texlive-xetex \
        texlive-collection-latexrecommended \
        texlive-collection-latexextra \
        texlive-collection-fontsrecommended \
        texlive-collection-fontsextra \
        texlive-latexmk \
        poppler-tools \
        fontconfig
}

install_macos() {
    if ! command -v brew >/dev/null 2>&1; then
        err "Homebrew not found. Install it from https://brew.sh then re-run."
        exit 1
    fi

    if command -v xelatex >/dev/null 2>&1 || [ -d /Library/TeX ]; then
        log "Existing TeX installation detected, skipping MacTeX cask."
    else
        run brew install --cask mactex-no-gui
    fi

    run brew install poppler

    local tlmgr=""
    if command -v tlmgr >/dev/null 2>&1; then
        tlmgr="tlmgr"
    elif [ -x /Library/TeX/texbin/tlmgr ]; then
        tlmgr="/Library/TeX/texbin/tlmgr"
        export PATH="/Library/TeX/texbin:$PATH"
    fi

    if [ -n "$tlmgr" ]; then
        run $SUDO "$tlmgr" update --self
        run $SUDO "$tlmgr" install \
            latexmk collection-xetex collection-fontsrecommended \
            fontspec unicode-math fontawesome5 sourcesanspro tcolorbox \
            enumitem ragged2e geometry fancyhdr xcolor xifthen etoolbox \
            setspace parskip hyperref iftex
    else
        err "tlmgr not found. Add /Library/TeX/texbin to PATH and re-run."
        exit 1
    fi
}

REQUIRED_STY="fontspec unicode-math fontawesome5 sourcesanspro tcolorbox \
enumitem ragged2e geometry fancyhdr xcolor xifthen etoolbox setspace \
parskip hyperref array"

verify() {
    local failures=0

    for cmd in xelatex latexmk kpsewhich; do
        if command -v "$cmd" >/dev/null 2>&1; then
            log "OK: $cmd -> $(command -v "$cmd")"
        else
            err "missing command: $cmd"
            failures=$((failures + 1))
        fi
    done

    if command -v pdfinfo >/dev/null 2>&1; then
        log "OK: pdfinfo -> $(command -v pdfinfo)"
    else
        log "WARN: pdfinfo not found (optional, used for page count metadata)"
    fi

    if command -v kpsewhich >/dev/null 2>&1; then
        for pkg in $REQUIRED_STY; do
            if kpsewhich "${pkg}.sty" >/dev/null 2>&1; then
                log "OK: ${pkg}.sty"
            else
                err "missing LaTeX package: ${pkg}"
                failures=$((failures + 1))
            fi
        done
    fi

    if [ "$failures" -ne 0 ]; then
        err "verification failed with $failures problem(s)"
        return 1
    fi

    log "verification passed"
    return 0
}

main() {
    if [ "$VERIFY_ONLY" -eq 1 ]; then
        verify
        exit $?
    fi

    local platform
    platform="$(detect_platform)"
    log "detected platform: $platform"

    case "$platform" in
        debian) install_debian ;;
        fedora) install_fedora ;;
        arch) install_arch ;;
        suse) install_suse ;;
        macos) install_macos ;;
        *)
            err "unsupported platform. See docs/LATEX_SETUP.md for manual steps."
            exit 1
            ;;
    esac

    if [ "$DRY_RUN" -eq 1 ]; then
        log "dry run complete"
        exit 0
    fi

    verify
}

main
