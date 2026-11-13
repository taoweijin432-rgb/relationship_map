#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/backend" && .venv/bin/ruff check src tests && .venv/bin/mypy src && .venv/bin/pytest -q)
bash "$ROOT/scripts/generate-api.sh"
(cd "$ROOT/frontend" && npm run format:check && npm run build && npm run test:e2e)
