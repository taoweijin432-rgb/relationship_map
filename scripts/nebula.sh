#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/infra/nebula/compose.yaml")
PYTHON="$ROOT/backend/.venv/bin/python"
case "${1:-status}" in
  up)
    "${COMPOSE[@]}" up -d
    "$PYTHON" "$ROOT/scripts/nebula_lab.py" bootstrap
    "${COMPOSE[@]}" up -d --wait --wait-timeout 120
    ;;
  status)
    "${COMPOSE[@]}" ps
    "$PYTHON" "$ROOT/scripts/nebula_lab.py" check
    ;;
  stop) "${COMPOSE[@]}" stop --timeout 30 ;;
  down) "${COMPOSE[@]}" down --timeout 30 ;;
  *) echo "用法：bash scripts/nebula.sh {up|status|stop|down}；停止／移除容器均保留数据卷。" >&2; exit 2 ;;
esac
