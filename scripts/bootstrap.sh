#!/usr/bin/env bash
# bootstrap.sh — Isolated mempalace-code install for any Linux/macOS machine.

set -euo pipefail

VENV="${MEMPALACE_VENV:-$HOME/.mempalace/venv}"
SOURCE="${MEMPALACE_SOURCE:-pypi}"
GIT_REF="${MEMPALACE_GIT_REF:-}"
GIT_REPO="https://github.com/rergards/mempalace-code.git"
BIN_LINK="$HOME/.local/bin/mempalace-code"
ALIAS_LINK="$HOME/.local/bin/mempalace"
MIN_PYTHON_MINOR=11

if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; NC=''
fi

info()  { printf "${GREEN}[+]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
fail()  { printf "${RED}[x]${NC} %s\n" "$*"; exit 1; }
inspection_command() { printf "ls -ld -- %q" "$1"; }

# Reject contradictory or mutable source selections before any filesystem mutation.
case "$SOURCE" in
    pypi)
        [ -z "$GIT_REF" ] || fail "MEMPALACE_GIT_REF is valid only with MEMPALACE_SOURCE=git"
        ;;
    git)
        [ -n "$GIT_REF" ] || fail "MEMPALACE_GIT_REF is required with MEMPALACE_SOURCE=git"
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
        ver=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
        if [ "$ver" -ge "$MIN_PYTHON_MINOR" ]; then
            PYTHON=$(command -v "$candidate")
            break
        fi
    fi
done
[ -n "$PYTHON" ] || fail "Python 3.11+ not found. Install it first."
PY_VER=$("$PYTHON" --version)
info "Using $PY_VER ($PYTHON)"
"$PYTHON" -c "import venv" 2>/dev/null \
    || fail "Python venv module missing. Install python3-venv (apt) or python3-libs (dnf)."

# In prepare mode, create missing components one at a time. Both modes reject
# redirected, foreign, irregular, or replaceable components and return identity.
directory_identity() {
    "$PYTHON" - "$1" "$2" <<'PY'
import os
import stat
import sys

path, mode = sys.argv[1:]
if mode not in ("prepare", "verify"):
    raise SystemExit(f"invalid directory identity mode: {mode}")
uid = os.getuid()
if not path.startswith("/") or os.path.normpath(path) != path or "\n" in path or "\r" in path:
    raise SystemExit(f"unsafe path spelling: {path}")

parts = [part for part in path.split("/") if part]
current = "/"
records = []
for part in parts:
    parent = current
    current = os.path.join(current, part)
    parent_stat = os.lstat(parent)
    if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
        raise SystemExit(f"unsafe path component: {parent}")
    if parent_stat.st_uid not in (0, uid):
        raise SystemExit(f"path component has foreign owner: {parent}")
    writable = bool(parent_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    try:
        node_stat = os.lstat(current)
    except FileNotFoundError:
        if mode == "verify":
            raise SystemExit(f"missing path component: {current}")
        if writable:
            raise SystemExit(f"missing component under replaceable directory: {current}")
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            pass
        node_stat = os.lstat(current)
    if writable:
        sticky = bool(parent_stat.st_mode & stat.S_ISVTX)
        if not sticky or node_stat.st_uid != uid:
            raise SystemExit(f"replaceable path component: {current}")
    if stat.S_ISLNK(node_stat.st_mode) or not stat.S_ISDIR(node_stat.st_mode):
        raise SystemExit(f"unsafe path component: {current}")
    if node_stat.st_uid not in (0, uid):
        raise SystemExit(f"path component has foreign owner: {current}")
    records.append(f"{current.encode().hex()}:{node_stat.st_dev}:{node_stat.st_ino}")
final_stat = os.lstat(path)
if final_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
    raise SystemExit(f"directory permits replacement of child entries: {path}")
print(";".join(records))
PY
}

VENV_PARENT=$(dirname "$VENV")
if ! PARENT_IDENTITY=$(directory_identity "$VENV_PARENT" prepare 2>&1); then
    fail "Unsafe MEMPALACE_VENV path $VENV: $PARENT_IDENTITY"
fi

LOCK="${VENV}.bootstrap.lock"
LOCK_TOKEN="$$.${RANDOM:-0}"
LOCK_ID=""
LOCK_ACQUIRING=0
LOCK_RECEIPT="$VENV_PARENT/.mempalace-bootstrap-receipt.${LOCK_TOKEN}"
exec 8>&- 9>&-

cleanup_lock() {
    "$PYTHON" - "$LOCK" "$LOCK_TOKEN" "$LOCK_ID" "$LOCK_ACQUIRING" \
        "$LOCK_RECEIPT" 8 9 <<'PY' >/dev/null 2>&1 || true
import os
import stat
import sys

path, expected_token, shell_id, acquiring, receipt_path, read_fd, write_fd = sys.argv[1:]
read_fd = int(read_fd)
write_fd = int(write_fd)

try:
    receipt_st = os.fstat(write_fd)
    linked_st = os.lstat(receipt_path)
    if (
        stat.S_ISREG(receipt_st.st_mode)
        and receipt_st.st_uid == os.getuid()
        and stat.S_IMODE(receipt_st.st_mode) == 0o600
        and (linked_st.st_dev, linked_st.st_ino) == (receipt_st.st_dev, receipt_st.st_ino)
    ):
        os.unlink(receipt_path)
except OSError:
    pass

try:
    os.lseek(read_fd, 0, os.SEEK_SET)
    receipt_lines = os.read(read_fd, 256).decode("ascii").splitlines()
except (OSError, UnicodeError):
    receipt_lines = []
original_id = receipt_lines[0] if len(receipt_lines) == 1 else ""

try:
    st = os.lstat(path)
    token_path = os.path.join(path, "token")
    token_st = os.lstat(token_path)
    with open(token_path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
except OSError:
    raise SystemExit(0)
expected_id = f"{st.st_dev}:{st.st_ino}"
metadata_id = lines[1] if len(lines) == 2 else ""
identity_matches = (
    bool(original_id)
    and lines[:1] == [expected_token]
    and metadata_id == original_id
    and expected_id == original_id
)
if acquiring != "1":
    identity_matches = identity_matches and bool(shell_id) and shell_id == original_id
valid = (
    stat.S_ISDIR(st.st_mode)
    and st.st_uid == os.getuid()
    and stat.S_IMODE(st.st_mode) == 0o700
    and stat.S_ISREG(token_st.st_mode)
    and token_st.st_uid == os.getuid()
    and stat.S_IMODE(token_st.st_mode) == 0o600
    and identity_matches
)
if valid:
    os.unlink(token_path)
    os.rmdir(path)
PY
}

terminate_on_signal() {
    trap - HUP INT TERM
    exit "$1"
}

trap cleanup_lock EXIT
trap 'terminate_on_signal 129' HUP
trap 'terminate_on_signal 130' INT
trap 'terminate_on_signal 143' TERM

umask 077
case $- in
    *C*) LOCK_NOCLOBBER_WAS_SET=1 ;;
    *) LOCK_NOCLOBBER_WAS_SET=0 ;;
esac
set -C
if ! exec 9>"$LOCK_RECEIPT"; then
    [ "$LOCK_NOCLOBBER_WAS_SET" = "1" ] || set +C
    fail "Could not create private bootstrap lock identity receipt: $LOCK_RECEIPT"
fi
[ "$LOCK_NOCLOBBER_WAS_SET" = "1" ] || set +C
exec 8<"$LOCK_RECEIPT" \
    || fail "Could not open private bootstrap lock identity receipt: $LOCK_RECEIPT"
"$PYTHON" - "$LOCK_RECEIPT" 8 9 <<'PY' \
    || fail "Could not verify private bootstrap lock identity receipt: $LOCK_RECEIPT"
import os
import stat
import sys

path, read_fd, write_fd = sys.argv[1:]
read_st = os.fstat(int(read_fd))
write_st = os.fstat(int(write_fd))
linked_st = os.lstat(path)
valid = (
    stat.S_ISREG(read_st.st_mode)
    and read_st.st_uid == os.getuid()
    and stat.S_IMODE(read_st.st_mode) == 0o600
    and (read_st.st_dev, read_st.st_ino) == (write_st.st_dev, write_st.st_ino)
    and (read_st.st_dev, read_st.st_ino) == (linked_st.st_dev, linked_st.st_ino)
)
if not valid:
    raise SystemExit(1)
os.unlink(path)
PY

LOCK_ACQUIRING=1
if ! (
    trap '' HUP INT TERM
    exec "$PYTHON" - "$LOCK" "$LOCK_TOKEN" acquire 9 <<'PY'
import os
import sys

path, token, _mode, receipt_fd = sys.argv[1:]
try:
    os.mkdir(path, 0o700)
except FileExistsError:
    raise SystemExit(1)

lock_st = os.lstat(path)
token_path = os.path.join(path, "token")
token_id = None
try:
    descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    token_id = os.fstat(descriptor)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"{token}\n{lock_st.st_dev}:{lock_st.st_ino}\n")
    os.write(int(receipt_fd), f"{lock_st.st_dev}:{lock_st.st_ino}\n".encode("ascii"))
    os.fsync(int(receipt_fd))
except BaseException:
    try:
        current = os.lstat(path)
        if (current.st_dev, current.st_ino) == (lock_st.st_dev, lock_st.st_ino):
            if token_id is not None:
                try:
                    current_token = os.lstat(token_path)
                    if (current_token.st_dev, current_token.st_ino) == (
                        token_id.st_dev,
                        token_id.st_ino,
                    ):
                        os.unlink(token_path)
                except FileNotFoundError:
                    pass
            os.rmdir(path)
    except OSError:
        pass
    raise
PY
); then
    LOCK_ACQUIRING=0
    fail "Bootstrap lock exists: $LOCK. Inspect and resolve, then retry: $(inspection_command "$LOCK")"
fi
exec 9>&-

snapshot_lock() {
    "$PYTHON" - "$LOCK" "$LOCK_TOKEN" 8 transition <<'PY'
import os
import stat
import sys

path, expected_token, receipt_fd, _mode = sys.argv[1:]
os.lseek(int(receipt_fd), 0, os.SEEK_SET)
receipt_lines = os.read(int(receipt_fd), 256).decode("ascii").splitlines()
if len(receipt_lines) != 1:
    raise SystemExit(1)
original_id = receipt_lines[0]
st = os.lstat(path)
token_path = os.path.join(path, "token")
token_st = os.lstat(token_path)
with open(token_path, encoding="utf-8") as handle:
    lines = handle.read().splitlines()
expected_id = f"{st.st_dev}:{st.st_ino}"
valid = (
    stat.S_ISDIR(st.st_mode)
    and st.st_uid == os.getuid()
    and stat.S_IMODE(st.st_mode) == 0o700
    and stat.S_ISREG(token_st.st_mode)
    and token_st.st_uid == os.getuid()
    and stat.S_IMODE(token_st.st_mode) == 0o600
    and expected_id == original_id
    and lines == [expected_token, original_id]
)
if not valid:
    raise SystemExit(1)
print(original_id)
PY
}

LOCK_ID=$(snapshot_lock) \
    || fail "Bootstrap lock identity changed: $LOCK. Inspect and resolve: $(inspection_command "$LOCK")"
LOCK_ACQUIRING=0

recheck_lock() {
    local current
    current=$(snapshot_lock) \
        || fail "Bootstrap lock identity changed: $LOCK. Inspect and resolve: $(inspection_command "$LOCK")"
    [ "$current" = "$LOCK_ID" ] \
        || fail "Bootstrap lock identity changed: $LOCK. Inspect and resolve: $(inspection_command "$LOCK")"
}

recheck_parent() {
    local current
    recheck_lock
    current=$(directory_identity "$VENV_PARENT" verify) \
        || fail "MEMPALACE_VENV parent identity check failed: $VENV_PARENT"
    [ "$current" = "$PARENT_IDENTITY" ] \
        || fail "MEMPALACE_VENV parent identity changed: $VENV_PARENT"
}

recheck_parent
if [ -e "$VENV" ] || [ -L "$VENV" ]; then
    [ -d "$VENV" ] && [ ! -L "$VENV" ] \
        || fail "Existing MEMPALACE_VENV is not a regular directory: $VENV"
    warn "Venv already exists at $VENV — validating for reuse"
else
    info "Creating venv at $VENV"
    "$PYTHON" -m venv "$VENV"
fi

VPYTHON="$VENV/bin/python"
VENV_BIN="$VENV/bin/mempalace-code"
VENV_MCP_BIN="$VENV/bin/mempalace-code-mcp"

snapshot_venv() {
    "$PYTHON" - "$VENV" "$VPYTHON" "$VENV_BIN" "$VENV_MCP_BIN" <<'PY'
import os
import stat
import sys

venv, python, *launchers = sys.argv[1:]
uid = os.getuid()
records = []
for path in (venv, os.path.join(venv, "bin"), python):
    st = os.lstat(path)
    if path != python and (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)):
        raise SystemExit(f"unsafe venv node: {path}")
    if path == python and not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
        raise SystemExit(f"unsafe venv interpreter: {path}")
    if st.st_uid != uid:
        raise SystemExit(f"venv node has foreign owner: {path}")
    if path != python and st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SystemExit(f"venv directory permits replacement: {path}")
    if path == python and not st.st_mode & stat.S_IXUSR:
        raise SystemExit(f"venv interpreter is not executable: {path}")
    records.append(f"{path.encode().hex()}:{st.st_dev}:{st.st_ino}")
resolved = os.path.realpath(python)
resolved_st = os.stat(resolved)
if not stat.S_ISREG(resolved_st.st_mode) or resolved_st.st_uid not in (0, uid):
    raise SystemExit(f"unsafe resolved venv interpreter: {resolved}")
records.append(f"{resolved.encode().hex()}:{resolved_st.st_dev}:{resolved_st.st_ino}")
for path in launchers:
    if not os.path.lexists(path):
        continue
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != uid:
        raise SystemExit(f"unsafe existing venv launcher: {path}")
    records.append(f"{path.encode().hex()}:{st.st_dev}:{st.st_ino}")
print(";".join(records))
PY
}

if ! VENV_IDENTITY=$(snapshot_venv 2>&1); then
    fail "Unsafe existing MEMPALACE_VENV $VENV: $VENV_IDENTITY"
fi

recheck_venv() {
    local parent current
    recheck_lock
    parent=$(directory_identity "$VENV_PARENT" verify) \
        || fail "MEMPALACE_VENV parent identity check failed: $VENV_PARENT"
    [ "$parent" = "$PARENT_IDENTITY" ] \
        || fail "MEMPALACE_VENV parent identity changed: $VENV_PARENT"
    current=$(snapshot_venv) || fail "MEMPALACE_VENV identity check failed: $VENV"
    [ "$current" = "$VENV_IDENTITY" ] \
        || fail "MEMPALACE_VENV identity changed: $VENV"
}

recheck_venv
PREFIX=$("$VPYTHON" -c "import os, sys; print(os.path.realpath(sys.prefix))") \
    || fail "Cannot query existing venv prefix: $VENV"
EXPECTED_PREFIX=$("$PYTHON" -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$VENV")
[ "$PREFIX" = "$EXPECTED_PREFIX" ] \
    || fail "Existing venv interpreter prefix mismatch: $VPYTHON reports $PREFIX, expected $EXPECTED_PREFIX"
recheck_venv

info "Upgrading pip inside venv"
"$VPYTHON" -m pip install --upgrade pip --quiet
recheck_venv

if [ "$SOURCE" = "git" ]; then
    info "Installing from git ($GIT_REPO@$GIT_REF)"
    "$VPYTHON" -m pip install "git+${GIT_REPO}@${GIT_REF}" --quiet
else
    info "Installing from PyPI"
    "$VPYTHON" -m pip install mempalace-code --quiet
fi

# Package installation may create or replace its own launchers. Establish the new
# authorized identity only after verifying their type, ownership, and executability.
recheck_lock
if ! VENV_IDENTITY=$(snapshot_venv 2>&1); then
    fail "Installed venv state is unsafe at $VENV: $VENV_IDENTITY"
fi
for launcher in "$VENV_BIN" "$VENV_MCP_BIN"; do
    [ -f "$launcher" ] && [ ! -L "$launcher" ] && [ -x "$launcher" ] \
        || fail "Installed launcher is missing or unsafe: $launcher"
done
recheck_venv

"$VPYTHON" -c "import mempalace_code; print(mempalace_code.__version__)" >/dev/null 2>&1 \
    || fail "Install succeeded but 'import mempalace_code' failed."
VERSION=$("$VPYTHON" -c "import mempalace_code; print(mempalace_code.__version__)")
recheck_venv
info "mempalace-code $VERSION installed"

BIN_DIR=$(dirname "$BIN_LINK")
if ! BIN_DIR_IDENTITY=$(directory_identity "$BIN_DIR" prepare 2>&1); then
    fail "Unsafe canonical launcher directory $BIN_DIR: $BIN_DIR_IDENTITY"
fi

recheck_bin_dir() {
    local current
    recheck_lock
    current=$(directory_identity "$BIN_DIR" verify 2>&1) \
        || fail "Canonical launcher directory identity check failed: $BIN_DIR. Inspect and resolve: $(inspection_command "$BIN_DIR")"
    [ "$current" = "$BIN_DIR_IDENTITY" ] \
        || fail "Canonical launcher directory identity changed: $BIN_DIR. Inspect and resolve: $(inspection_command "$BIN_DIR")"
}

publish_symlink() {
    local target="$1" destination="$2" result
    if result=$("$PYTHON" - "$target" "$destination" <<'PY'
import errno
import os
import sys

target, destination = sys.argv[1:]
try:
    os.symlink(target, destination)
    print("created")
except OSError as exc:
    if exc.errno != errno.EEXIST:
        raise
    if os.path.islink(destination) and os.path.realpath(destination) == os.path.realpath(target):
        print("correct")
    else:
        print("collision")
PY
    ); then
        case "$result" in
            created) info "Symlinked $destination -> $target" ;;
            correct) info "Symlink already correct: $destination" ;;
            collision)
                fail "Refusing to replace existing launcher $destination. Inspect and resolve, then retry: $(inspection_command "$destination")"
                ;;
            *) fail "Unexpected launcher publication result for $destination" ;;
        esac
    else
        fail "Could not publish launcher $destination"
    fi
}

recheck_venv
recheck_bin_dir
publish_symlink "$VENV_BIN" "$BIN_LINK"

# Preserve the optional alias policy: any existing command or node remains untouched.
if command -v mempalace >/dev/null 2>&1; then
    warn "Leaving existing mempalace command untouched: $(command -v mempalace)"
elif [ -e "$ALIAS_LINK" ] || [ -L "$ALIAS_LINK" ]; then
    warn "Leaving existing $ALIAS_LINK untouched"
else
    recheck_bin_dir
    if ALIAS_RESULT=$("$PYTHON" - "$BIN_LINK" "$ALIAS_LINK" <<'PY'
import errno
import os
import sys
try:
    os.symlink(sys.argv[1], sys.argv[2])
    print("created")
except OSError as exc:
    if exc.errno != errno.EEXIST:
        raise
    print("collision")
PY
    ); then
        if [ "$ALIAS_RESULT" = "created" ]; then
            info "Optional alias: $ALIAS_LINK -> $BIN_LINK"
        else
            warn "A concurrent node won the optional alias race; leaving $ALIAS_LINK untouched"
        fi
    else
        fail "Could not publish optional alias $ALIAS_LINK"
    fi
fi

if ! echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
    warn "$HOME/.local/bin is not on PATH"
    warn "Add to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

recheck_venv
recheck_bin_dir
CANONICAL_TARGET=$("$PYTHON" -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$BIN_LINK")
EXPECTED_TARGET=$("$PYTHON" -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$VENV_BIN")
[ -L "$BIN_LINK" ] && [ "$CANONICAL_TARGET" = "$EXPECTED_TARGET" ] \
    || fail "Canonical launcher post-state verification failed: $BIN_LINK"
PREFIX=$("$VPYTHON" -c "import os, sys; print(os.path.realpath(sys.prefix))")
[ "$PREFIX" = "$EXPECTED_PREFIX" ] || fail "Venv prefix changed before completion: $VENV"
recheck_venv
"$VENV_BIN" --version >/dev/null 2>&1 || fail "Installed launcher smoke failed: $VENV_BIN"
"$VENV_MCP_BIN" --help >/dev/null 2>&1 || fail "Installed MCP launcher smoke failed: $VENV_MCP_BIN"
recheck_venv

printf "\n"
info "Done. mempalace-code $VERSION is ready."
info "Venv:   $VENV"
info "Binary: $BIN_LINK"
info "Owner:  $VENV_BIN"
info "MCP:    $VENV_MCP_BIN"
info "Notification state: unchanged (set before init with: $VENV_BIN version-check --enable|--disable)"
info "Scheduled updates: disabled unless separately enabled with: $VENV_BIN update scheduler install --yes"
info "Next:   $VENV_BIN init <project-dir> --skip-model-download"
