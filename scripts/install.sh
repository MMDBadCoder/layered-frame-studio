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
Usage: sudo ./scripts/install.sh [options]

  --port <n>       service port (default: 8080, or the value found in .env)
  --host <ip>      bind address (default: 0.0.0.0)
  --user <name>    user the service runs as (default: the project directory's owner)
  --debug          run the service in DEBUG mode (development only)
  --skip-apt       skip installing system packages
  -h, --help       this help
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
    *) die "unknown option: $1  (see --help)" ;;
  esac
done

require_root "$@"

printf '%s\n' "${C_BOLD}Installing Photo Frame 2D${C_RESET}"
info "project directory: $PROJECT_DIR"
info "port: $PORT"

# --- 1. system packages ------------------------------------------------------

step "Checking system packages"
if [ "$SKIP_APT" -eq 1 ]; then
  info "skipped (--skip-apt)"
else
  MISSING=()
  dpkg -s python3-venv >/dev/null 2>&1 || MISSING+=(python3-venv)
  dpkg -s python3-pip  >/dev/null 2>&1 || MISSING+=(python3-pip)
  have curl || MISSING+=(curl)

  if [ ${#MISSING[@]} -eq 0 ]; then
    ok "all required packages are already installed"
  else
    info "installing: ${MISSING[*]}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq "${MISSING[@]}"
    ok "system packages installed"
  fi
fi

have python3 || die "python3 was not found on this system."
info "$(python3 --version)"

# --- 2. virtualenv -----------------------------------------------------------

step "Preparing the Python virtualenv"
if [ ! -x "$PYTHON_BIN" ]; then
  python3 -m venv "$VENV_DIR"
  ok "virtualenv created: $VENV_DIR"
else
  ok "virtualenv already exists"
fi

"$PIP_BIN" install --quiet --upgrade pip setuptools wheel
info "installing dependencies (this can take a few minutes)…"
"$PIP_BIN" install --quiet -r "${PROJECT_DIR}/requirements.txt"
ok "dependencies are up to date"

# --- 3. .env -----------------------------------------------------------------

step "Configuration (.env)"
if [ ! -f "$ENV_FILE" ]; then
  SECRET="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(64))')"
  cat > "$ENV_FILE" <<EOF
# Photo Frame 2D — runtime environment settings
# This file holds the application's secret key; never publish it.
PHOTO_FRAME_SECRET_KEY=${SECRET}
PHOTO_FRAME_DEBUG=${WANT_DEBUG}
PHOTO_FRAME_PORT=${PORT}
EOF
  chmod 600 "$ENV_FILE"
  ok ".env created (a random secret key was generated)"
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
  ok "existing .env kept (secret key untouched)"
fi

# --- 4. database & static ----------------------------------------------------

step "Database and static files"
cd "$PROJECT_DIR"
"$PYTHON_BIN" manage.py migrate --noinput
ok "database migrations applied"

PHOTO_FRAME_DEBUG=0 "$PYTHON_BIN" manage.py collectstatic --noinput --clear >/dev/null
ok "static files collected"

mkdir -p "$STATE_MEDIA" "$STATE_UPLOADS"

# --- 5. ownership ------------------------------------------------------------

step "File ownership"
if [ -z "$RUN_AS" ]; then
  RUN_AS="$(stat -c '%U' "$PROJECT_DIR")"
fi
id "$RUN_AS" >/dev/null 2>&1 || die "no such user: $RUN_AS"
RUN_GROUP="$(id -gn "$RUN_AS")"
chown -R "$RUN_AS:$RUN_GROUP" "$STATE_MEDIA" "$STATE_UPLOADS" 2>/dev/null || true
[ -f "$STATE_DB" ] && chown "$RUN_AS:$RUN_GROUP" "$STATE_DB"
chown "$RUN_AS:$RUN_GROUP" "$ENV_FILE"
ok "the service will run as $RUN_AS"

# --- 6. systemd service ------------------------------------------------------

step "systemd service"
if ! has_systemd; then
  warn "systemd is not available; skipping this step."
  warn "start the app manually:  ./run.sh"
else
  WORKERS="$(( $(nproc 2>/dev/null || echo 1) * 2 + 1 ))"
  [ "$WORKERS" -gt 5 ] && WORKERS=5   # image work is CPU-heavy and memory-hungry

  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Photo Frame 2D — layered photo frame studio
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
  ok "service ${SERVICE_NAME} installed and started (${WORKERS} workers)"
fi

# --- 7. firewall -------------------------------------------------------------

step "Firewall"
if have ufw; then
  ufw allow "${PORT}/tcp" comment "Photo Frame 2D" >/dev/null 2>&1 || true
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    ok "ufw rule for port ${PORT} is active"
  else
    ok "ufw rule for port ${PORT} added (ufw is currently disabled)"
    info "to enable it:  ufw allow OpenSSH && ufw enable"
  fi
else
  info "ufw is not installed; skipping this step."
fi

# --- 8. health check ---------------------------------------------------------

step "Health check"
HEALTH_URL="http://127.0.0.1:${PORT}/"
if wait_for_http "$HEALTH_URL" 40; then
  ok "the application responds"
else
  warn "the application did not respond within 40 seconds."
  if has_systemd; then
    warn "most recent errors:"
    journalctl -u "$SERVICE_NAME" -n 25 --no-pager || true
  fi
  die "installation did not complete."
fi

IP="$(primary_ip)"
ADMIN_COUNT="$("$PYTHON_BIN" -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','photoframe.settings'); django.setup()
from accounts.models import User
print(User.objects.filter(is_superuser=True).count())
" 2>/dev/null || echo 0)"

cat <<EOF

${C_GREEN}${C_BOLD}Installation completed successfully.${C_RESET}

  Application    : http://${IP:-127.0.0.1}:${PORT}/
  Admin panel    : http://${IP:-127.0.0.1}:${PORT}/admin/
  Service status : systemctl status ${SERVICE_NAME}
  Live logs      : journalctl -u ${SERVICE_NAME} -f
EOF

if [ "$ADMIN_COUNT" = "0" ]; then
  cat <<EOF

  ${C_YELLOW}No admin user exists yet.${C_RESET}
  Create one with:  sudo ./scripts/create-admin.sh
EOF
fi
echo
