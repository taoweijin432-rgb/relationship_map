#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/resources"
"$ROOT/backend/.venv/bin/python" -m relationship_query.cli export-openapi > "$ROOT/resources/openapi.json"
(cd "$ROOT/frontend" && npm run generate:api)
