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

need_cmd git

run_git_network() {
  if ! git "$@"; then
    echo >&2
    echo "GitHub connection failed. If your network needs a proxy, retry with:" >&2
    echo '  XBOT_PROXY="http://127.0.0.1:7897" curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.sh | bash' >&2
    echo >&2
    return 1
  fi
}

run_git() {
  git "$@"
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
  echo "Updating xbot-next in $INSTALL_DIR"
  run_git_network -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"

  local remote_ref="origin/$BRANCH"
  local local_head remote_head status backup_branch
  local_head="$(git -C "$INSTALL_DIR" rev-parse HEAD)"
  remote_head="$(git -C "$INSTALL_DIR" rev-parse "$remote_ref")"
  status="$(git -C "$INSTALL_DIR" status --porcelain)"

  if [ "$local_head" != "$remote_head" ] || [ -n "$status" ]; then
    backup_branch="xbot-local-backup-$(date +%Y%m%d%H%M%S)"
    run_git -C "$INSTALL_DIR" branch "$backup_branch" HEAD
    echo "Install repo has local changes or diverged commits." >&2
    echo "Backed up current HEAD to branch $backup_branch, then upgrading to $remote_ref." >&2
    if [ -n "$status" ]; then
      run_git -C "$INSTALL_DIR" stash push -m "xbot install backup before upgrade" || true
    fi
    run_git -C "$INSTALL_DIR" reset --hard
  fi

  run_git -C "$INSTALL_DIR" checkout -B "$BRANCH" "$remote_ref"
}

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

mkdir -p "$(dirname "$INSTALL_DIR")" "$BIN_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  update_install_repo
else
  echo "Installing xbot-next to $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  run_git_network clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
install_build_tools
python -m pip install --no-build-isolation -e .

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created $INSTALL_DIR/.env from .env.example"
fi

python -m playwright install chromium || true

cat > "$BIN_DIR/xbot" <<EOF
#!/usr/bin/env bash
set -e
cd "$INSTALL_DIR"
exec "$INSTALL_DIR/.venv/bin/xbot" "\$@"
EOF
chmod +x "$BIN_DIR/xbot"

if [ "${XBOT_SKIP_SETUP:-0}" != "1" ]; then
  echo
  echo "Starting xbot setup..."
  if [ -r /dev/tty ] && [ -w /dev/tty ]; then
    "$INSTALL_DIR/.venv/bin/xbot" setup < /dev/tty
  else
    "$INSTALL_DIR/.venv/bin/xbot" setup --yes
  fi
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    SHELL_RC=""
    if [ -n "${ZSH_VERSION:-}" ]; then
      SHELL_RC="$HOME/.zshrc"
    elif [ -n "${BASH_VERSION:-}" ]; then
      SHELL_RC="$HOME/.bashrc"
    elif [ -f "$HOME/.profile" ]; then
      SHELL_RC="$HOME/.profile"
    fi
    if [ -n "$SHELL_RC" ] && [ -w "$(dirname "$SHELL_RC")" ]; then
      touch "$SHELL_RC"
      if ! grep -F "$BIN_DIR" "$SHELL_RC" >/dev/null 2>&1; then
        printf '\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$SHELL_RC"
        echo "Added $BIN_DIR to PATH in $SHELL_RC"
      fi
    fi
    export PATH="$BIN_DIR:$PATH"
    ;;
esac

echo
echo "xbot installed."
echo "Install dir: $INSTALL_DIR"
echo "Command: $BIN_DIR/xbot"
echo "Upgrade: curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.sh | bash"
echo 'Upgrade with proxy: XBOT_PROXY="http://127.0.0.1:7897" curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.sh | bash'
echo
echo "Next steps:"
echo "  1. Edit $INSTALL_DIR/.env if needed"
echo "  2. Open a new terminal if xbot is not on PATH yet"
echo "  3. Run: xbot        # enter TUI"
echo "  4. Run: xbot run    # start backend service"
