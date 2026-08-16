#!/usr/bin/env bash
#
# Photo Frame 2D — full installer for Ubuntu/Debian servers.
#
# Idempotent: run it as often as you like. It installs system packages, builds
# the virtualenv, applies migrations, collects static files, writes a systemd
# unit and makes sure the service is up. Nothing is destroyed; existing data,
# .env and the database are always left alone.
#
#   sudo ./scripts/install.sh
#   sudo ./scripts/install.sh --port 9000 --debug
#
# Safe to run before OR after restoring a backup.
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

PORT="$(app_port)"
BIND_HOST="$DEFAULT_HOST"
WANT_DEBUG=0
SKIP_APT=0
RUN_AS=""

usage() {
  cat <<'USAGE'
استفاده: sudo ./scripts/install.sh [گزینه‌ها]

  --port <n>       پورت سرویس (پیش‌فرض: 8080، یا مقدار موجود در .env)
  --host <ip>      آدرس bind (پیش‌فرض: 0.0.0.0)
  --user <name>    کاربری که سرویس با آن اجرا می‌شود (پیش‌فرض: مالک پوشهٔ پروژه)
  --debug          اجرای سرویس در حالت DEBUG (فقط برای توسعه)
  --skip-apt       نصب بسته‌های سیستمی را رد کن
  -h, --help       همین راهنما
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --host) BIND_HOST="${2:?--host needs a value}"; shift 2 ;;
    --user) RUN_AS="${2:?--user needs a value}"; shift 2 ;;
    --debug) WANT_DEBUG=1; shift ;;
    --skip-apt) SKIP_APT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "گزینهٔ ناشناخته: $1  (--help را ببینید)" ;;
  esac
done

require_root "$@"

printf '%s\n' "${C_BOLD}نصب Photo Frame 2D${C_RESET}"
info "پوشهٔ پروژه: $PROJECT_DIR"
info "پورت: $PORT"

# --- 1. system packages ------------------------------------------------------

step "بررسی بسته‌های سیستمی"
if [ "$SKIP_APT" -eq 1 ]; then
  info "رد شد (--skip-apt)"
else
  MISSING=()
  dpkg -s python3-venv >/dev/null 2>&1 || MISSING+=(python3-venv)
  dpkg -s python3-pip  >/dev/null 2>&1 || MISSING+=(python3-pip)
  have curl || MISSING+=(curl)

  if [ ${#MISSING[@]} -eq 0 ]; then
    ok "همهٔ بسته‌های لازم از قبل نصب هستند"
  else
    info "نصب: ${MISSING[*]}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq "${MISSING[@]}"
    ok "بسته‌های سیستمی نصب شدند"
  fi
fi

have python3 || die "python3 روی این سیستم پیدا نشد."
info "$(python3 --version)"

# --- 2. virtualenv -----------------------------------------------------------

step "آماده‌سازی محیط مجازی پایتون"
if [ ! -x "$PYTHON_BIN" ]; then
  python3 -m venv "$VENV_DIR"
  ok "محیط مجازی ساخته شد: $VENV_DIR"
else
  ok "محیط مجازی از قبل وجود دارد"
fi

"$PIP_BIN" install --quiet --upgrade pip setuptools wheel
info "نصب وابستگی‌ها (ممکن است چند دقیقه طول بکشد)…"
"$PIP_BIN" install --quiet -r "${PROJECT_DIR}/requirements.txt"
ok "وابستگی‌ها به‌روز هستند"

# --- 3. .env -----------------------------------------------------------------

step "پیکربندی (.env)"
if [ ! -f "$ENV_FILE" ]; then
  SECRET="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(64))')"
  cat > "$ENV_FILE" <<EOF
# Photo Frame 2D — تنظیمات محیط اجرا
# این فایل شامل کلید امنیتی برنامه است؛ آن را منتشر نکنید.
PHOTO_FRAME_SECRET_KEY=${SECRET}
PHOTO_FRAME_DEBUG=${WANT_DEBUG}
PHOTO_FRAME_PORT=${PORT}
EOF
  chmod 600 "$ENV_FILE"
  ok "فایل .env ساخته شد (کلید امنیتی تصادفی تولید شد)"
else
  # Keep the existing secret; only refresh the operational values.
  "$PYTHON_BIN" - "$ENV_FILE" "$PORT" "$WANT_DEBUG" <<'PY'
import sys
from pathlib import Path

path, port, debug = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
values = {"PHOTO_FRAME_PORT": port, "PHOTO_FRAME_DEBUG": debug}
seen = set()
out = []

for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in values:
        out.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        out.append(line)

for key, value in values.items():
    if key not in seen:
        out.append(f"{key}={value}")

path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  chmod 600 "$ENV_FILE"
  ok "فایل .env موجود حفظ شد (کلید امنیتی دست‌نخورده)"
fi

# --- 4. database & static ----------------------------------------------------

step "پایگاه داده و فایل‌های ایستا"
cd "$PROJECT_DIR"
"$PYTHON_BIN" manage.py migrate --noinput
ok "مهاجرت‌های پایگاه داده اعمال شد"

PHOTO_FRAME_DEBUG=0 "$PYTHON_BIN" manage.py collectstatic --noinput --clear >/dev/null
ok "فایل‌های ایستا جمع‌آوری شد"

mkdir -p "$STATE_MEDIA" "$STATE_UPLOADS"

# --- 5. ownership ------------------------------------------------------------

step "مالکیت فایل‌ها"
if [ -z "$RUN_AS" ]; then
  RUN_AS="$(stat -c '%U' "$PROJECT_DIR")"
fi
id "$RUN_AS" >/dev/null 2>&1 || die "کاربر «$RUN_AS» وجود ندارد."
RUN_GROUP="$(id -gn "$RUN_AS")"
chown -R "$RUN_AS:$RUN_GROUP" "$STATE_MEDIA" "$STATE_UPLOADS" 2>/dev/null || true
[ -f "$STATE_DB" ] && chown "$RUN_AS:$RUN_GROUP" "$STATE_DB"
chown "$RUN_AS:$RUN_GROUP" "$ENV_FILE"
ok "سرویس با کاربر «$RUN_AS» اجرا می‌شود"

# --- 6. systemd service ------------------------------------------------------

step "سرویس systemd"
if ! has_systemd; then
  warn "systemd در دسترس نیست؛ از این مرحله صرف‌نظر شد."
  warn "برنامه را دستی اجرا کنید:  ./run.sh"
else
  WORKERS="$(( $(nproc 2>/dev/null || echo 1) * 2 + 1 ))"
  [ "$WORKERS" -gt 5 ] && WORKERS=5   # image work is CPU-heavy and memory-hungry

  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Photo Frame 2D — استودیو ساخت تصاویر لایه‌ای
Documentation=file://${PROJECT_DIR}/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_AS}
Group=${RUN_GROUP}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/gunicorn photoframe.wsgi:application \\
    --bind ${BIND_HOST}:${PORT} \\
    --workers ${WORKERS} \\
    --timeout 300 \\
    --graceful-timeout 30 \\
    --access-logfile - \\
    --error-logfile -
Restart=always
RestartSec=3
KillSignal=SIGTERM

# Image processing is the whole job here, so give it room but keep it bounded.
LimitNOFILE=8192

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --quiet "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  ok "سرویس ${SERVICE_NAME} نصب و راه‌اندازی شد (${WORKERS} worker)"
fi

# --- 7. firewall -------------------------------------------------------------

step "فایروال"
if have ufw; then
  ufw allow "${PORT}/tcp" comment "Photo Frame 2D" >/dev/null 2>&1 || true
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    ok "قانون ufw برای پورت ${PORT} فعال است"
  else
    ok "قانون ufw برای پورت ${PORT} ثبت شد (ufw هم‌اکنون غیرفعال است)"
    info "برای فعال‌سازی:  ufw allow OpenSSH && ufw enable"
  fi
else
  info "ufw نصب نیست؛ از این مرحله صرف‌نظر شد."
fi

# --- 8. health check ---------------------------------------------------------

step "بررسی سلامت"
HEALTH_URL="http://127.0.0.1:${PORT}/"
if wait_for_http "$HEALTH_URL" 40; then
  ok "برنامه پاسخ می‌دهد"
else
  warn "برنامه در ۴۰ ثانیه پاسخ نداد."
  if has_systemd; then
    warn "آخرین خطاها:"
    journalctl -u "$SERVICE_NAME" -n 25 --no-pager || true
  fi
  die "نصب کامل نشد."
fi

IP="$(primary_ip)"
ADMIN_COUNT="$("$PYTHON_BIN" -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','photoframe.settings'); django.setup()
from accounts.models import User
print(User.objects.filter(is_superuser=True).count())
" 2>/dev/null || echo 0)"

cat <<EOF

${C_GREEN}${C_BOLD}نصب با موفقیت انجام شد.${C_RESET}

  آدرس برنامه   : http://${IP:-127.0.0.1}:${PORT}/
  پنل مدیریت    : http://${IP:-127.0.0.1}:${PORT}/admin/
  وضعیت سرویس   : systemctl status ${SERVICE_NAME}
  لاگ زنده      : journalctl -u ${SERVICE_NAME} -f
EOF

if [ "$ADMIN_COUNT" = "0" ]; then
  cat <<EOF

  ${C_YELLOW}هنوز هیچ کاربر مدیری وجود ندارد.${C_RESET}
  برای ساخت مدیر:  sudo ./scripts/create-admin.sh
EOF
fi
echo
