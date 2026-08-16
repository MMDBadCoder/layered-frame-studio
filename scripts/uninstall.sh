#!/usr/bin/env bash
#
# Photo Frame 2D — remove the systemd service.
#
# By default ONLY the service is removed. Your database, uploaded images and
# .env are never touched unless you explicitly ask for it.
#
#   sudo ./scripts/uninstall.sh                # stop + disable + remove unit
#   sudo ./scripts/uninstall.sh --purge-venv   # …and delete .venv
#   sudo ./scripts/uninstall.sh --purge-data   # …and delete ALL data (asks first)
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

PURGE_VENV=0
PURGE_DATA=0
REMOVE_UFW=0
ASSUME_YES=0

usage() {
  cat <<'USAGE'
استفاده: sudo ./scripts/uninstall.sh [گزینه‌ها]

  --purge-venv     پوشهٔ .venv هم حذف شود
  --purge-data     پایگاه داده، تصاویر و .env هم حذف شوند (خطرناک)
  --remove-ufw     قانون ufw مربوط به پورت برنامه حذف شود
  --yes            بدون پرسش تأیید ادامه بده
  -h, --help       همین راهنما

داده‌ها به‌صورت پیش‌فرض حفظ می‌شوند.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --purge-venv) PURGE_VENV=1; shift ;;
    --purge-data) PURGE_DATA=1; shift ;;
    --remove-ufw) REMOVE_UFW=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "گزینهٔ ناشناخته: $1  (--help را ببینید)" ;;
  esac
done

require_root "$@"

step "توقف سرویس"
if has_systemd && service_installed; then
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable --quiet "$SERVICE_NAME" 2>/dev/null || true
  rm -f "$SERVICE_FILE"
  systemctl daemon-reload
  systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
  ok "سرویس ${SERVICE_NAME} متوقف و حذف شد"
else
  info "سرویسی برای حذف پیدا نشد"
fi

if [ "$REMOVE_UFW" -eq 1 ] && have ufw; then
  step "فایروال"
  PORT="$(app_port)"
  ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true
  ok "قانون ufw پورت ${PORT} حذف شد"
fi

if [ "$PURGE_VENV" -eq 1 ]; then
  step "حذف محیط مجازی"
  rm -rf "$VENV_DIR"
  ok "پوشهٔ .venv حذف شد"
fi

if [ "$PURGE_DATA" -eq 1 ]; then
  step "حذف کامل داده‌ها"
  warn "این کار پایگاه داده، تصاویر سفارش‌ها و کلید امنیتی را برای همیشه حذف می‌کند."
  info "مسیرها: $STATE_DB، $STATE_MEDIA، $STATE_UPLOADS، $ENV_FILE"

  if [ "$ASSUME_YES" -ne 1 ]; then
    printf '    برای تأیید، عبارت %sDELETE%s را تایپ کنید: ' "$C_BOLD" "$C_RESET"
    read -r CONFIRM
    [ "$CONFIRM" = "DELETE" ] || die "لغو شد؛ هیچ داده‌ای حذف نشد."
  fi

  info "ابتدا یک نسخهٔ پشتیبان گرفته می‌شود…"
  if "${PROJECT_DIR}/scripts/backup.sh" --quiet; then
    ok "پشتیبان‌گیری انجام شد (قبل از حذف)"
  else
    warn "پشتیبان‌گیری ناموفق بود؛ ادامه داده می‌شود."
  fi

  rm -f "$STATE_DB" "$ENV_FILE"
  rm -rf "$STATE_MEDIA" "$STATE_UPLOADS" "${PROJECT_DIR}/staticfiles"
  ok "همهٔ داده‌ها حذف شدند"
fi

cat <<EOF

${C_GREEN}${C_BOLD}حذف سرویس انجام شد.${C_RESET}
EOF

if [ "$PURGE_DATA" -eq 0 ]; then
  cat <<EOF
  داده‌های شما دست‌نخورده باقی ماند:
    پایگاه داده : $STATE_DB
    تصاویر      : $STATE_MEDIA
  برای نصب دوباره:  sudo ./scripts/install.sh
EOF
fi
echo
