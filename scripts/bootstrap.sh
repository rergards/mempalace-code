#!/usr/bin/env bash
# Isolated mempalace-code install for Linux and macOS.

set -euo pipefail

VENV="${MEMPALACE_VENV:-$HOME/.mempalace/venv}"
SOURCE="${MEMPALACE_SOURCE:-pypi}"
GIT_REF="${MEMPALACE_GIT_REF:-}"
GIT_REPO="https://github.com/rergards/mempalace-code.git"
BIN_DIR="$HOME/.local/bin"
BIN_LINK="$BIN_DIR/mempalace-code"
ALIAS_LINK="$BIN_DIR/mempalace"

if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; NC=''
fi
info() { printf "${GREEN}[+]${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
fail() { printf "${RED}[x]${NC} %s\n" "$*"; exit 1; }

case "$SOURCE" in
    pypi)
        [ -z "$GIT_REF" ] || fail "MEMPALACE_GIT_REF is valid only with MEMPALACE_SOURCE=git"
        ;;
    git)
        [[ "$GIT_REF" =~ ^[0-9a-fA-F]{40}$ ]] \
            || fail "MEMPALACE_GIT_REF must be a full 40-hex commit"
        ;;
    *) fail "Unknown MEMPALACE_SOURCE=$SOURCE; expected pypi or git" ;;
esac

case "$VENV" in
    /*) ;;
    *) fail "MEMPALACE_VENV must be an absolute path: $VENV" ;;
esac

PYTHON=""
for candidate in python3 python python3.14 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
        minor=$("$candidate" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
        if [ "$minor" -ge 11 ]; then
            PYTHON=$(command -v "$candidate")
            break
        fi
    fi
done
[ -n "$PYTHON" ] || fail "Python 3.11+ not found. Install it first."
"$PYTHON" -c 'import venv' 2>/dev/null \
    || fail "Python venv module missing. Install python3-venv (apt) or python3-libs (dnf)."
info "Using $("$PYTHON" --version) ($PYTHON)"

if [ -L "$VENV" ] || { [ -e "$VENV" ] && [ ! -d "$VENV" ]; }; then
    fail "MEMPALACE_VENV must be a real directory or an absent path: $VENV"
fi
if [ ! -e "$VENV" ]; then
    info "Creating venv at $VENV"
    "$PYTHON" -m venv "$VENV"
else
    warn "Venv already exists at $VENV; validating for reuse"
fi

VPYTHON="$VENV/bin/python"
VENV_BIN="$VENV/bin/mempalace-code"
VENV_MCP_BIN="$VENV/bin/mempalace-code-mcp"
[ -x "$VPYTHON" ] || fail "Existing venv has no executable Python: $VPYTHON"
ACTUAL_PREFIX=$("$VPYTHON" -c 'import os,sys; print(os.path.realpath(sys.prefix))')
EXPECTED_PREFIX=$("$PYTHON" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$VENV")
[ "$ACTUAL_PREFIX" = "$EXPECTED_PREFIX" ] \
    || fail "Existing venv prefix mismatch: expected $EXPECTED_PREFIX, got $ACTUAL_PREFIX"

info "Upgrading pip inside venv"
"$VPYTHON" -m pip install --upgrade pip --quiet
if [ "$SOURCE" = "git" ]; then
    info "Installing reviewed commit $GIT_REF"
    "$VPYTHON" -m pip install "git+${GIT_REPO}@${GIT_REF}" --quiet
else
    info "Installing from PyPI"
    "$VPYTHON" -m pip install mempalace-code --quiet
fi

[ -x "$VENV_BIN" ] || fail "Installed launcher is missing: $VENV_BIN"
[ -x "$VENV_MCP_BIN" ] || fail "Installed MCP launcher is missing: $VENV_MCP_BIN"
VERSION=$("$VENV_BIN" --version) || fail "Installed launcher smoke failed"

mkdir -p "$BIN_DIR"
if [ -L "$BIN_LINK" ] && [ "$(readlink "$BIN_LINK")" = "$VENV_BIN" ]; then
    info "Symlink already correct: $BIN_LINK"
elif [ -e "$BIN_LINK" ] || [ -L "$BIN_LINK" ]; then
    fail "Refusing to replace existing launcher $BIN_LINK. Move it aside, then rerun."
else
    ln -s "$VENV_BIN" "$BIN_LINK"
    info "Symlinked $BIN_LINK -> $VENV_BIN"
fi

if command -v mempalace >/dev/null 2>&1; then
    warn "Leaving existing mempalace command untouched: $(command -v mempalace)"
elif [ -e "$ALIAS_LINK" ] || [ -L "$ALIAS_LINK" ]; then
    warn "Leaving existing $ALIAS_LINK untouched"
else
    ln -s "$BIN_LINK" "$ALIAS_LINK"
    info "Optional alias: $ALIAS_LINK -> $BIN_LINK"
fi

if ! printf '%s' "$PATH" | tr ':' '\n' | grep -Fqx "$BIN_DIR"; then
    warn "$BIN_DIR is not on PATH"
    warn "Add to your shell profile: export PATH=\"$BIN_DIR:\$PATH\""
fi

"$VENV_BIN" version-check --status
"$VENV_BIN" update status
printf '\n'
info "Done. $VERSION is ready."
info "Binary: $BIN_LINK"
info "Version notifications: unchanged; choose with $VENV_BIN version-check --enable|--disable"
info "Scheduled package updates: disabled unless enabled with $VENV_BIN update scheduler install --yes"
info "Next: $VENV_BIN init <project-dir> --skip-model-download"
info "Update: $VENV_BIN update apply --yes"
