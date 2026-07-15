#!/usr/bin/env bash
# Import LinkedIn posts/articles into Writing/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/import-linkedin.py" "$@"
