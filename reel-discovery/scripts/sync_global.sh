#!/usr/bin/env bash
#
# Sync the reel-discovery skill between this (project-local) copy and the global
# Cursor copy at ~/.cursor/skills/reel-discovery so both stay identical.
#
#   ./sync_global.sh            # push: this copy  -> global   (default)
#   ./sync_global.sh --pull     # pull: global     -> this copy
#   ./sync_global.sh --dry-run  # show what would change, do nothing
#
# Never synced (each location keeps its own): config.json (secrets),
# __pycache__/, *.pyc, discovery/ (research output), .DS_Store.
#
# Note: avoids `set -u` so an empty optional-args array expands cleanly on
# macOS's default bash 3.2.
set -eo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GLOBAL_DIR="$HOME/.cursor/skills/reel-discovery"

DIRECTION="push"
DRY=()
for arg in "$@"; do
  case "$arg" in
    --pull) DIRECTION="pull" ;;
    --dry-run) DRY=(--dry-run --itemize-changes) ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

EXCLUDES=(
  --exclude='config.json'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='discovery/'
  --exclude='.DS_Store'
)

if [[ "$SKILL_DIR" == "$GLOBAL_DIR" ]]; then
  echo "This IS the global copy ($GLOBAL_DIR)."
  echo "Run sync_global.sh from the project-local copy instead."
  exit 0
fi

mkdir -p "$GLOBAL_DIR"
if [[ "$DIRECTION" == "push" ]]; then
  echo "Push: $SKILL_DIR/ -> $GLOBAL_DIR/"
  rsync -a --delete "${DRY[@]}" "${EXCLUDES[@]}" "$SKILL_DIR/" "$GLOBAL_DIR/"
else
  echo "Pull: $GLOBAL_DIR/ -> $SKILL_DIR/"
  rsync -a --delete "${DRY[@]}" "${EXCLUDES[@]}" "$GLOBAL_DIR/" "$SKILL_DIR/"
fi
echo "Done. (config.json, __pycache__/, discovery/ are not synced.)"
