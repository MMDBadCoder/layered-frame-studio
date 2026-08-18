#!/usr/bin/env bash
#
# Photo Frame 3D — package everything worth keeping into one .zip.
#
# Captures the database, all order images, live session renders and the secret
# key. Safe to run while the service is up (the database is snapshotted with
# SQLite's online backup API, not copied byte-for-byte).
#
#   ./scripts/backup.sh                        # -> backups/photo-frame-3d-backup-<date>.zip
#   ./scripts/backup.sh --output /mnt/nas/pf.zip
#   ./scripts/backup.sh --no-uploads --no-env
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

OUTPUT=""
BACKUP_DIR="${PROJECT_DIR}/backups"
EXTRA_ARGS=()
QUIET=0
KEEP=0

usage() {
  cat <<'USAGE'
Usage: ./scripts/backup.sh [options]

  --output <path>   output file path (default: backups/photo-frame-3d-backup-<date>.zip)
  --dir <path>      directory to write backups into
  --no-uploads      exclude the temporary files in uploads/
  --no-env          exclude the .env file (the secret key)
  --keep <n>        keep only the n newest backups and delete the rest
  --quiet           less output
  -h, --help        this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --output) OUTPUT="${2:?--output needs a value}"; shift 2 ;;
    --dir) BACKUP_DIR="${2:?--dir needs a value}"; shift 2 ;;
    --no-uploads) EXTRA_ARGS+=(--no-uploads); shift ;;
    --no-env) EXTRA_ARGS+=(--no-env); shift ;;
    --keep) KEEP="${2:?--keep needs a value}"; shift 2 ;;
    --quiet|-q) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1  (see --help)" ;;
  esac
done

if [ -z "$OUTPUT" ]; then
  mkdir -p "$BACKUP_DIR"
  OUTPUT="${BACKUP_DIR}/photo-frame-3d-backup-$(date +%Y%m%d-%H%M%S).zip"
fi

# The helper is stdlib-only, so fall back to the system python if the
# virtualenv is missing — a backup must work even on a broken install.
PY="$PYTHON_BIN"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "python3 not found; cannot take a backup."

[ "$QUIET" -eq 1 ] || step "Creating a backup"

RESULT="$("$PY" "${PROJECT_DIR}/scripts/_backup.py" \
  --project-dir "$PROJECT_DIR" \
  --output "$OUTPUT" \
  ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"})"

if [ "$QUIET" -eq 0 ]; then
  "$PY" - "$RESULT" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
counts = data.get("counts") or {}
print(f"    output file : {data['output']}")
print(f"    size        : {data['size_mb']} MB  ({data['files']} files)")
if counts:
    print(f"    contents    : {counts.get('users')} users, "
          f"{counts.get('orders')} orders, {counts.get('color_profiles')} colour profiles")
PY
  ok "backup complete"
fi

# Retention: keep only the newest N archives. The glob is deliberately loose
# so archives named before the 2D->3D rename are still pruned.
if [ "$KEEP" -gt 0 ] && [ -d "$BACKUP_DIR" ]; then
  mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/photo-frame-*-backup-*.zip 2>/dev/null | tail -n +$((KEEP + 1)))
  if [ ${#OLD[@]} -gt 0 ]; then
    rm -f "${OLD[@]}"
    [ "$QUIET" -eq 1 ] || info "${#OLD[@]} old backup(s) deleted (keeping: $KEEP)"
  fi
fi

# Machine-readable last line, handy for cron/monitoring.
echo "$OUTPUT"
