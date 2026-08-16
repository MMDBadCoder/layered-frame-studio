#!/usr/bin/env bash
# Shared helpers for the Photo Frame 2D maintenance scripts.
# Sourced by install.sh / uninstall.sh / backup.sh / restore.sh / create-admin.sh.

set -euo pipefail

# Resolve the project root from this file's location, so every script can be
# invoked from anywhere (including via an absolute path or a symlink).
_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$_COMMON_DIR/.." && pwd)"

APP_NAME="photo-frame-2d"
SERVICE_NAME="${APP_NAME}.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"

VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"
ENV_FILE="${PROJECT_DIR}/.env"

# State that must survive a reinstall and be captured by backups.
STATE_DB="${PROJECT_DIR}/db.sqlite3"
STATE_MEDIA="${PROJECT_DIR}/media"
STATE_UPLOADS="${PROJECT_DIR}/uploads"

DEFAULT_PORT=8080
DEFAULT_HOST=0.0.0.0

# --- output ------------------------------------------------------------------

if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

step()  { printf '\n%s==>%s %s%s%s\n' "$C_BLUE" "$C_RESET" "$C_BOLD" "$*" "$C_RESET"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '    %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()   { printf '\n%serror:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

# --- guards ------------------------------------------------------------------

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "این اسکریپت باید با دسترسی root اجرا شود.  →  sudo $0 $*"
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }

has_systemd() { have systemctl && [ -d /run/systemd/system ]; }

# --- env file ----------------------------------------------------------------

# Read a single key out of .env (empty string when absent).
env_get() {
  local key="$1"
  [ -f "$ENV_FILE" ] || { echo ""; return; }
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -1
}

app_port() {
  local port
  port="$(env_get PHOTO_FRAME_PORT)"
  echo "${port:-$DEFAULT_PORT}"
}

# --- service -----------------------------------------------------------------

service_installed() { [ -f "$SERVICE_FILE" ]; }
service_active()    { has_systemd && systemctl is-active --quiet "$SERVICE_NAME"; }

# Poll the HTTP endpoint until it answers or we run out of patience.
wait_for_http() {
  local url="$1" attempts="${2:-30}" i
  for i in $(seq 1 "$attempts"); do
    if have curl && curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# The primary non-loopback address, for printing a reachable URL.
primary_ip() {
  if have hostname; then
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}
