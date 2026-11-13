#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v uv >/dev/null || { echo "请先安装 uv；后端依赖将安装在 backend/.venv。" >&2; exit 1; }
command -v npm >/dev/null || { echo "请先安装 Node.js 22.12+ 和 npm。" >&2; exit 1; }
uv sync --project "$ROOT/backend" --python "${PYTHON_VERSION:-3.12}" --locked
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
bash "$ROOT/scripts/generate-api.sh"
"$ROOT/backend/.venv/bin/python" -m relationship_query.cli init
echo "依赖与模拟数据已就绪。运行 bash scripts/dev.sh 启动。"
