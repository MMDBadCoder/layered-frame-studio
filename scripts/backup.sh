#!/usr/bin/env bash
#
# Photo Frame 2D — package everything worth keeping into one .zip.
#
# Captures the database, all order images, live session renders and the secret
# key. Safe to run while the service is up (the database is snapshotted with
# SQLite's online backup API, not copied byte-for-byte).
#
#   ./scripts/backup.sh                        # -> backups/photo-frame-2d-backup-<date>.zip
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
استفاده: ./scripts/backup.sh [گزینه‌ها]

  --output <path>   مسیر فایل خروجی (پیش‌فرض: backups/photo-frame-2d-backup-<تاریخ>.zip)
  --dir <path>      پوشهٔ مقصد پشتیبان‌ها
  --no-uploads      فایل‌های موقت uploads/ را شامل نشو
  --no-env          فایل .env (کلید امنیتی) را شامل نشو
  --keep <n>        فقط n پشتیبان آخر را نگه دار و بقیه را حذف کن
  --quiet           خروجی کمتر
  -h, --help        همین راهنما
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
    *) die "گزینهٔ ناشناخته: $1  (--help را ببینید)" ;;
  esac
done

if [ -z "$OUTPUT" ]; then
  mkdir -p "$BACKUP_DIR"
  OUTPUT="${BACKUP_DIR}/photo-frame-2d-backup-$(date +%Y%m%d-%H%M%S).zip"
fi

# The helper is stdlib-only, so fall back to the system python if the
# virtualenv is missing — a backup must work even on a broken install.
PY="$PYTHON_BIN"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "python3 پیدا نشد؛ پشتیبان‌گیری ممکن نیست."

[ "$QUIET" -eq 1 ] || step "ساخت نسخهٔ پشتیبان"

RESULT="$("$PY" "${PROJECT_DIR}/scripts/_backup.py" \
  --project-dir "$PROJECT_DIR" \
  --output "$OUTPUT" \
  ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"})"

if [ "$QUIET" -eq 0 ]; then
  "$PY" - "$RESULT" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
counts = data.get("counts") or {}
print(f"    فایل خروجی : {data['output']}")
print(f"    حجم        : {data['size_mb']} مگابایت  ({data['files']} فایل)")
if counts:
    print(f"    محتوا      : {counts.get('users')} کاربر، "
          f"{counts.get('orders')} سفارش، {counts.get('color_profiles')} پروفایل رنگی")
PY
  ok "پشتیبان‌گیری کامل شد"
fi

# Retention: keep only the newest N archives in the backup directory.
if [ "$KEEP" -gt 0 ] && [ -d "$BACKUP_DIR" ]; then
  mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/photo-frame-2d-backup-*.zip 2>/dev/null | tail -n +$((KEEP + 1)))
  if [ ${#OLD[@]} -gt 0 ]; then
    rm -f "${OLD[@]}"
    [ "$QUIET" -eq 1 ] || info "${#OLD[@]} پشتیبان قدیمی حذف شد (نگه‌داری: $KEEP)"
  fi
fi

# Machine-readable last line, handy for cron/monitoring.
echo "$OUTPUT"
