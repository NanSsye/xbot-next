#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${XBOT_REPO_URL:-https://github.com/NanSsye/xbot-next.git}"
BRANCH="${XBOT_BRANCH:-main}"

if [ -n "${XBOT_PROXY:-}" ]; then
  export HTTP_PROXY="$XBOT_PROXY"
  export HTTPS_PROXY="$XBOT_PROXY"
  export ALL_PROXY="$XBOT_PROXY"
  echo "Using proxy from XBOT_PROXY: $XBOT_PROXY"
fi

if [ "$(id -u)" -eq 0 ]; then
  INSTALL_DIR="${XBOT_INSTALL_DIR:-/usr/local/lib/xbot-next}"
  BIN_DIR="${XBOT_BIN_DIR:-/usr/local/bin}"
else
  INSTALL_DIR="${XBOT_INSTALL_DIR:-$HOME/.xbot/xbot-next}"
  BIN_DIR="${XBOT_BIN_DIR:-$HOME/.local/bin}"
fi

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

run_git_network() {
  if ! git "$@"; then
    echo >&2
    echo "GitHub connection failed. If your network needs a proxy, retry with:" >&2
    echo '  XBOT_PROXY="http://127.0.0.1:7897" curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/upgrade.sh | bash' >&2
    echo >&2
    return 1
  fi
}

install_build_tools() {
  if python -m pip install -U setuptools wheel; then
    return 0
  fi

  echo "Current pip index failed to install setuptools/wheel, retrying with PyPI." >&2
  if python -m pip install -U --index-url https://pypi.org/simple setuptools wheel; then
    return 0
  fi

  echo >&2
  echo "Failed to install build tools. Check your proxy or pip index, then retry:" >&2
  echo "  python -m pip install -U --index-url https://pypi.org/simple setuptools wheel" >&2
  echo >&2
  return 1
}

update_install_repo() {
  echo "Upgrading xbot-next in $INSTALL_DIR"
  echo "Protected user data: .env, data/, logs/, local database files, untracked uploads and generated skills."
  run_git_network -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"

  local remote_ref="origin/$BRANCH"
  local local_head remote_head status backup_branch
  local_head="$(git -C "$INSTALL_DIR" rev-parse HEAD)"
  remote_head="$(git -C "$INSTALL_DIR" rev-parse "$remote_ref")"
  status="$(git -C "$INSTALL_DIR" status --porcelain)"

  if [ "$local_head" != "$remote_head" ] || [ -n "$status" ]; then
    backup_branch="xbot-local-backup-$(date +%Y%m%d%H%M%S)"
    git -C "$INSTALL_DIR" branch "$backup_branch" HEAD
    echo "Install repo has local changes or diverged commits." >&2
    echo "Backed up current HEAD to branch $backup_branch, then upgrading to $remote_ref." >&2
    if [ -n "$status" ]; then
      git -C "$INSTALL_DIR" stash push -m "xbot upgrade backup before reset" || true
    fi
    git -C "$INSTALL_DIR" reset --hard
  fi

  git -C "$INSTALL_DIR" checkout -B "$BRANCH" "$remote_ref"
}

need_cmd git

if [ ! -d "$INSTALL_DIR/.git" ]; then
  echo "xbot is not installed as a git checkout at $INSTALL_DIR." >&2
  echo "Run install.sh for first install; upgrade will not overwrite this directory." >&2
  exit 1
fi

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Missing Python 3.11+. Please install Python 3.11 or newer." >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required.")
PY

update_install_repo
cd "$INSTALL_DIR"

if [ ! -f .env ]; then
  echo ".env not found. Upgrade will not create or overwrite user config; run xbot setup if you need to initialize config." >&2
fi

"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
install_build_tools
python -m pip install --no-build-isolation -e .
python -m playwright install chromium || true

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/xbot" <<EOF
#!/usr/bin/env bash
set -e
cd "$INSTALL_DIR"
exec "$INSTALL_DIR/.venv/bin/xbot" "\$@"
EOF
chmod +x "$BIN_DIR/xbot"

cat > "$BIN_DIR/xbot-upgrade" <<EOF
#!/usr/bin/env bash
set -e
exec "$INSTALL_DIR/scripts/upgrade.sh" "\$@"
EOF
chmod +x "$BIN_DIR/xbot-upgrade"

echo
echo "xbot upgraded."
echo "Install dir: $INSTALL_DIR"
echo "Protected: .env and user data were not overwritten or deleted."
echo "Command: $BIN_DIR/xbot"
echo "Upgrade command: $BIN_DIR/xbot-upgrade"
