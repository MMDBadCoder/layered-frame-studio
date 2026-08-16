#!/usr/bin/env bash
#
# Photo Frame 2D — restore state from a backup archive.
#
# Takes the .zip produced by backup.sh and injects the whole state back into
# the application: database, order images, live renders and the secret key.
#
#   sudo ./scripts/restore.sh backups/photo-frame-2d-backup-20260817-0130.zip
#   ./scripts/restore.sh --inspect <file.zip>     # just show what is inside
#
# Before overwriting anything it takes a safety snapshot of the CURRENT state,
# so a mistaken restore is always reversible.
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

ARCHIVE=""
INSPECT=0
SKIP_ENV=0
ASSUME_YES=0
NO_SAFETY=0

usage() {
  cat <<'USAGE'
استفاده: sudo ./scripts/restore.sh <فایل-پشتیبان.zip> [گزینه‌ها]

  --inspect        فقط محتوای پشتیبان را نشان بده و خارج شو
  --skip-env       فایل .env فعلی حفظ شود (کلید امنیتی جایگزین نشود)
  --no-safety      نسخهٔ ایمنی از وضعیت فعلی گرفته نشود (توصیه نمی‌شود)
  --yes            بدون پرسش تأیید ادامه بده
  -h, --help       همین راهنما
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --inspect) INSPECT=1; shift ;;
    --skip-env) SKIP_ENV=1; shift ;;
    --no-safety) NO_SAFETY=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) die "گزینهٔ ناشناخته: $1  (--help را ببینید)" ;;
    *) ARCHIVE="$1"; shift ;;
  esac
done

[ -n "$ARCHIVE" ] || { usage; die "مسیر فایل پشتیبان را وارد کنید."; }
[ -f "$ARCHIVE" ] || die "فایل پیدا نشد: $ARCHIVE"
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

PY="$PYTHON_BIN"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "python3 پیدا نشد."

# --- inspect only ------------------------------------------------------------

if [ "$INSPECT" -eq 1 ]; then
  "$PY" "${PROJECT_DIR}/scripts/_restore.py" \
    --project-dir "$PROJECT_DIR" --archive "$ARCHIVE" --inspect
  exit 0
fi

require_root "$@"

step "بررسی فایل پشتیبان"
MANIFEST="$("$PY" "${PROJECT_DIR}/scripts/_restore.py" \
  --project-dir "$PROJECT_DIR" --archive "$ARCHIVE" --inspect)"

"$PY" - "$MANIFEST" <<'PY'
import json, sys
m = json.loads(sys.argv[1])
counts = m.get("counts") or {}
print(f"    تاریخ ساخت : {m.get('created_at')}")
print(f"    مبدأ       : {m.get('hostname')}  ({m.get('source_project_dir')})")
print(f"    محتوا      : {counts.get('users')} کاربر، "
      f"{counts.get('orders')} سفارش، {counts.get('color_profiles')} پروفایل رنگی")
print(f"    شامل .env  : {'بله' if m.get('includes_env') else 'خیر'}")
PY
ok "فایل پشتیبان معتبر است"

if [ "$ASSUME_YES" -ne 1 ]; then
  warn "بازیابی، پایگاه دادهٔ فعلی و تصاویر سفارش‌ها را جایگزین می‌کند."
  printf '    برای ادامه %sRESTORE%s را تایپ کنید: ' "$C_BOLD" "$C_RESET"
  read -r CONFIRM
  [ "$CONFIRM" = "RESTORE" ] || die "لغو شد؛ هیچ تغییری اعمال نشد."
fi

# --- safety snapshot ---------------------------------------------------------

if [ "$NO_SAFETY" -eq 0 ]; then
  step "نسخهٔ ایمنی از وضعیت فعلی"
  SAFETY="${PROJECT_DIR}/backups/pre-restore-$(date +%Y%m%d-%H%M%S).zip"
  if "${PROJECT_DIR}/scripts/backup.sh" --output "$SAFETY" --quiet >/dev/null; then
    ok "وضعیت فعلی ذخیره شد: $SAFETY"
  else
    warn "گرفتن نسخهٔ ایمنی ناموفق بود."
    [ "$ASSUME_YES" -eq 1 ] || die "برای ادامه بدون نسخهٔ ایمنی از --no-safety استفاده کنید."
  fi
fi

# --- stop, restore, start ----------------------------------------------------

WAS_RUNNING=0
if service_active; then
  WAS_RUNNING=1
  step "توقف موقت سرویس"
  systemctl stop "$SERVICE_NAME"
  ok "سرویس متوقف شد"
fi

step "بازیابی وضعیت"
RESTORE_ARGS=(--project-dir "$PROJECT_DIR" --archive "$ARCHIVE")
[ "$SKIP_ENV" -eq 1 ] && RESTORE_ARGS+=(--skip-env)

RESULT="$("$PY" "${PROJECT_DIR}/scripts/_restore.py" "${RESTORE_ARGS[@]}")"
ok "پایگاه داده و فایل‌ها بازیابی شدند"

# Ownership must match whatever the service runs as, or gunicorn cannot write.
RUN_AS="$(stat -c '%U' "$PROJECT_DIR")"
if service_installed; then
  UNIT_USER="$(sed -n 's/^User=//p' "$SERVICE_FILE" | tail -1)"
  [ -n "$UNIT_USER" ] && RUN_AS="$UNIT_USER"
fi
RUN_GROUP="$(id -gn "$RUN_AS" 2>/dev/null || echo "$RUN_AS")"
chown -R "$RUN_AS:$RUN_GROUP" "$STATE_MEDIA" "$STATE_UPLOADS" 2>/dev/null || true
[ -f "$STATE_DB" ] && chown "$RUN_AS:$RUN_GROUP" "$STATE_DB"
[ -f "$ENV_FILE" ] && chown "$RUN_AS:$RUN_GROUP" "$ENV_FILE" && chmod 600 "$ENV_FILE"
ok "مالکیت فایل‌ها برای کاربر «$RUN_AS» تنظیم شد"

# An older backup may predate newer migrations.
if [ -x "$PYTHON_BIN" ]; then
  step "هم‌سان‌سازی ساختار پایگاه داده"
  cd "$PROJECT_DIR"
  "$PYTHON_BIN" manage.py migrate --noinput
  ok "مهاجرت‌ها اعمال شد"
else
  warn ".venv پیدا نشد؛ مهاجرت‌ها اجرا نشدند. ابتدا ./scripts/install.sh را اجرا کنید."
fi

if [ "$WAS_RUNNING" -eq 1 ] || service_installed; then
  step "راه‌اندازی مجدد سرویس"
  systemctl start "$SERVICE_NAME"
  PORT="$(app_port)"
  if wait_for_http "http://127.0.0.1:${PORT}/" 40; then
    ok "برنامه با وضعیت بازیابی‌شده در حال اجراست"
  else
    warn "برنامه پاسخ نداد؛ لاگ را بررسی کنید:  journalctl -u ${SERVICE_NAME} -n 50"
  fi
fi

echo
printf '%s%sبازیابی با موفقیت انجام شد.%s\n' "$C_GREEN" "$C_BOLD" "$C_RESET"
"$PY" - "$RESULT" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
counts = d.get("counts") or {}
print(f"    منبع  : {d['restored_from']}")
print(f"    تاریخ : {d.get('created_at')}")
print(f"    محتوا : {counts.get('users')} کاربر، {counts.get('orders')} سفارش")
PY
echo
