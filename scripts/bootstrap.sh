#!/usr/bin/env bash
# bootstrap.sh — Isolated mempalace-code install for any Linux/macOS machine.
#
# Creates a venv, upgrades pip inside it, installs mempalace-code, and symlinks
# the canonical binary so it's on PATH. Sidesteps old-system-pip and hatchling issues.
#
# Usage:
#   curl -fsSL <raw-url>/scripts/bootstrap.sh | bash
#   # or
#   bash scripts/bootstrap.sh
#
# Options (env vars):
#   MEMPALACE_VENV=~/.mempalace/venv   # venv location (default)
#   MEMPALACE_SOURCE=pypi               # "pypi" or "git" (default: pypi)
#   MEMPALACE_GIT_REF=main              # git branch/tag (only if SOURCE=git)

set -euo pipefail

# --- Config ---
VENV="${MEMPALACE_VENV:-$HOME/.mempalace/venv}"
SOURCE="${MEMPALACE_SOURCE:-pypi}"
GIT_REF="${MEMPALACE_GIT_REF:-main}"
GIT_REPO="https://github.com/rergards/mempalace-code.git"
BIN_LINK="$HOME/.local/bin/mempalace-code"
ALIAS_LINK="$HOME/.local/bin/mempalace"
MIN_PYTHON_MINOR=11

# --- Colors (if terminal) ---
if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; NC=''
fi

info()  { printf "${GREEN}[+]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
fail()  { printf "${RED}[x]${NC} %s\n" "$*"; exit 1; }

# --- Step 1: Find Python 3.11+ ---
PYTHON=""
for candidate in python3 python python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.minor}')" 2>/dev/null || echo "0")
        if [ "$ver" -ge "$MIN_PYTHON_MINOR" ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

[ -z "$PYTHON" ] && fail "Python 3.11+ not found. Install it first."
PY_VER=$("$PYTHON" --version)
info "Using $PY_VER ($PYTHON)"

# --- Step 2: Check for venv module ---
"$PYTHON" -c "import venv" 2>/dev/null || fail "Python venv module missing. Install python3-venv (apt) or python3-libs (dnf)."

# --- Step 3: Create venv ---
if [ -d "$VENV" ]; then
    warn "Venv already exists at $VENV — reusing"
else
    info "Creating venv at $VENV"
    "$PYTHON" -m venv "$VENV"
fi

VPYTHON="$VENV/bin/python"
VPIP="$VENV/bin/pip"

# --- Step 4: Upgrade pip inside venv ---
info "Upgrading pip inside venv"
"$VPYTHON" -m pip install --upgrade pip --quiet

# --- Step 5: Install mempalace-code ---
if [ "$SOURCE" = "git" ]; then
    info "Installing from git ($GIT_REPO@$GIT_REF)"
    "$VPIP" install "git+${GIT_REPO}@${GIT_REF}" --quiet
else
    info "Installing from PyPI"
    "$VPIP" install mempalace-code --quiet
fi

# --- Step 6: Verify import ---
"$VPYTHON" -c "import mempalace; print(mempalace.__version__)" >/dev/null 2>&1 \
    || fail "Install succeeded but 'import mempalace' failed."

VERSION=$("$VPYTHON" -c "import mempalace; print(mempalace.__version__)")
info "mempalace-code $VERSION installed"

# --- Step 7: Symlink canonical binary to ~/.local/bin ---
mkdir -p "$(dirname "$BIN_LINK")"
VENV_BIN="$VENV/bin/mempalace-code"

if [ -L "$BIN_LINK" ] || [ -e "$BIN_LINK" ]; then
    EXISTING=$(readlink -f "$BIN_LINK" 2>/dev/null || echo "unknown")
    if [ "$EXISTING" = "$(readlink -f "$VENV_BIN")" ]; then
        info "Symlink already correct: $BIN_LINK"
    else
        warn "Replacing existing $BIN_LINK (was: $EXISTING)"
        ln -sf "$VENV_BIN" "$BIN_LINK"
    fi
else
    ln -s "$VENV_BIN" "$BIN_LINK"
    info "Symlinked $BIN_LINK -> $VENV_BIN"
fi

# --- Step 8: Optional legacy alias, only when unused ---
if command -v mempalace >/dev/null 2>&1; then
    warn "Leaving existing mempalace command untouched: $(command -v mempalace)"
elif [ -L "$ALIAS_LINK" ] || [ -e "$ALIAS_LINK" ]; then
    warn "Leaving existing $ALIAS_LINK untouched"
else
    ln -s "$BIN_LINK" "$ALIAS_LINK"
    info "Optional alias: $ALIAS_LINK -> $BIN_LINK"
fi

# --- Step 9: PATH check ---
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
    warn "$HOME/.local/bin is not on PATH"
    warn "Add to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# --- Step 10: Smoke test ---
info "Running smoke test..."
export PATH="$HOME/.local/bin:$PATH"

if mempalace-code status >/dev/null 2>&1 || mempalace-code status 2>&1 | grep -q "No palace found"; then
    info "mempalace-code status: OK"
else
    warn "mempalace-code status returned unexpected output (may be fine on first run)"
fi

# --- Done ---
printf "\n"
info "Done. mempalace-code $VERSION is ready."
info "Venv:   $VENV"
info "Binary: $BIN_LINK"
info "Next:   mempalace-code init <project-dir> && mempalace-code mine <project-dir>"
