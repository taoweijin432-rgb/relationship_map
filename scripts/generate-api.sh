#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/backend/.venv/bin/python" -m relationship_query.cli export-openapi > "$ROOT/docs/openapi.json"
(cd "$ROOT/frontend" && npm run generate:api)
