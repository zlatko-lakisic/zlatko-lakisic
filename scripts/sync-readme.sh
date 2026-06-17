#!/usr/bin/env bash
# Sync index.md (GitHub Pages source of truth) -> README.md (GitHub repo blob URLs)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INDEX="$ROOT/index.md"
README="$ROOT/README.md"
BASE="https://github.com/zlatko-lakisic/zlatko-lakisic/blob/main"

[[ -f "$INDEX" ]] || { echo "Missing $INDEX" >&2; exit 1; }

content="$(cat "$INDEX")"
content="$(sed -E "s|]\\(/zlatko-lakisic/Projects\\.html#([^)]+)\\)|]($BASE/Projects.md#\\1)|g" <<< "$content")"
content="$(sed "s|](/zlatko-lakisic/Projects\\.html)|]($BASE/Projects.md)|g" <<< "$content")"
content="$(sed "s|](\\./Resume\\.md#|]($BASE/Resume.md#|g" <<< "$content")"
content="$(sed "s|](\\./Resume\\.md)|]($BASE/Resume.md)|g" <<< "$content")"
content="$(sed "s|](\\./Technical-Strategy\\.md#|]($BASE/Technical-Strategy.md#|g" <<< "$content")"
content="$(sed "s|](\\./Technical-Strategy\\.md)|]($BASE/Technical-Strategy.md)|g" <<< "$content")"
content="$(sed "s|](\\./Recommendations/README\\.md)|]($BASE/Recommendations/README.md)|g" <<< "$content")"
content="$(sed -E "s|]\\(\\./Recommendations/([^)#]+)\\)|]($BASE/Recommendations/\\1)|g" <<< "$content")"
content="$(sed -E "s|]\\(\\./Projects\\.md#([^)]+)\\)|]($BASE/Projects.md#\\1)|g" <<< "$content")"
content="$(sed "s|](\\./Projects\\.md)|]($BASE/Projects.md)|g" <<< "$content")"
content="$(sed -E "s|]\\(\\./Engineering/([^)#]+)\\)|]($BASE/Engineering/\\1)|g" <<< "$content")"
content="$(sed -E "s|]\\(\\./Healthcare/([^)#]+)\\)|]($BASE/Healthcare/\\1)|g" <<< "$content")"
content="$(sed -E "s|]\\(\\./Identity/([^)#]+)\\)|]($BASE/Identity/\\1)|g" <<< "$content")"
content="$(sed "s|](\\./index\\.md)|]($BASE/index.md)|g" <<< "$content")"
content="$(sed "s|](LICENSE)|]($BASE/LICENSE)|g" <<< "$content")"
content="$(sed -E "s|href=\"\\./Projects\\.md#([^\"]+)\"|href=\"$BASE/Projects.md#\\1\"|g" <<< "$content")"
content="$(sed -E "s|href=\"\\./Engineering/([^\"]+)\"|href=\"$BASE/Engineering/\\1\"|g" <<< "$content")"

{
  echo "<!-- AUTO-GENERATED from index.md. Do not edit README.md directly. Run: scripts/sync-readme.sh -->"
  echo ""
  printf '%s' "$content"
} > "$README"

echo "Synced README.md from index.md"
