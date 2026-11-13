#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -x "$ROOT/backend/.venv/bin/python" ] || [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "请先运行 bash scripts/setup.sh。后端须使用 backend/.venv 虚拟环境。" >&2
  exit 1
fi
exec "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/dev.py"
