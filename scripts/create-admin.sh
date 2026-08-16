#!/usr/bin/env bash
#
# Photo Frame 2D — create or promote a super admin.
#
#   ./scripts/create-admin.sh
#   ./scripts/create-admin.sh --phone 09121234567 --email a@b.com --generate-password
#
# With no arguments it asks for the details interactively. If the phone number
# already belongs to a customer, that account is promoted and its orders are
# left untouched.
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'USAGE'
استفاده: ./scripts/create-admin.sh [گزینه‌ها]

  --phone <09…>          شماره موبایل مدیر
  --email <a@b.com>      ایمیل
  --name  "نام"          نام و نام خانوادگی
  --generate-password    رمز تصادفی بساز و نمایش بده
  --password <pass>      رمز مشخص (در تاریخچهٔ شل باقی می‌ماند)
  --noinput              بدون پرسش تعاملی

بدون گزینه، اطلاعات به‌صورت تعاملی پرسیده می‌شود.
USAGE
  exit 0
fi

[ -x "$PYTHON_BIN" ] || die "محیط مجازی پیدا نشد. ابتدا اجرا کنید:  sudo ./scripts/install.sh"

cd "$PROJECT_DIR"
exec "$PYTHON_BIN" manage.py create_admin "$@"
