#!/usr/bin/env sh
set -eu

cd /app

mkdir -p /app/data /app/logs /app/workspace /app/data/.docker

hash_files() {
  python - "$@" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(".")
digest = hashlib.sha256()
for pattern in sys.argv[1:]:
    for path in sorted(root.glob(pattern)):
        if path.is_file():
            digest.update(str(path).encode("utf-8", "ignore"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
print(digest.hexdigest())
PY
}

if [ "${XBOT_DOCKER_INSTALL_DEPS_ON_START:-true}" = "true" ]; then
  py_hash="$(hash_files pyproject.toml)"
  py_marker="/app/data/.docker/pyproject.sha256"
  if [ ! -f "$py_marker" ] || [ "$(cat "$py_marker")" != "$py_hash" ]; then
    echo "[xbot-docker] 安装/更新 Python 依赖..."
    python -m pip install -e .
    echo "$py_hash" > "$py_marker"
  fi
fi

if [ "${XBOT_DOCKER_BUILD_UI_ON_START:-true}" = "true" ]; then
  ui_hash="$(hash_files 'ui/package.json' 'ui/package-lock.json' 'ui/tsconfig.json' 'ui/vite.config.ts' 'ui/index.html' 'ui/src/**')"
  ui_marker="/app/data/.docker/ui.sha256"
  if [ ! -f "$ui_marker" ] || [ "$(cat "$ui_marker")" != "$ui_hash" ] || [ ! -f /app/ui/dist/index.html ]; then
    echo "[xbot-docker] 构建 Web 控制台..."
    cd /app/ui
    if [ -f package-lock.json ]; then
      npm ci
    else
      npm install
    fi
    npm run build
    cd /app
    echo "$ui_hash" > "$ui_marker"
  fi
fi

exec "$@"
