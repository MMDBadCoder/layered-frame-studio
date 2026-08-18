#!/usr/bin/env bash
#
# Photo Frame 3D — remove the systemd service.
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
Usage: sudo ./scripts/uninstall.sh [options]

  --purge-venv     also delete the .venv directory
  --purge-data     also delete the database, the images and .env (dangerous)
  --remove-ufw     also remove the ufw rule for the app's port
  --yes            proceed without asking for confirmation
  -h, --help       this help

Data is kept by default.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --purge-venv) PURGE_VENV=1; shift ;;
    --purge-data) PURGE_DATA=1; shift ;;
    --remove-ufw) REMOVE_UFW=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1  (see --help)" ;;
  esac
done

require_root "$@"

step "Stopping the service"
retire_legacy_service
if has_systemd && service_installed; then
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable --quiet "$SERVICE_NAME" 2>/dev/null || true
  rm -f "$SERVICE_FILE"
  systemctl daemon-reload
  systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
  ok "service ${SERVICE_NAME} stopped and removed"
else
  info "no service found to remove"
fi

if [ "$REMOVE_UFW" -eq 1 ] && have ufw; then
  step "Firewall"
  PORT="$(app_port)"
  ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true
  ok "ufw rule for port ${PORT} removed"
fi

if [ "$PURGE_VENV" -eq 1 ]; then
  step "Removing the virtualenv"
  rm -rf "$VENV_DIR"
  ok ".venv removed"
fi

if [ "$PURGE_DATA" -eq 1 ]; then
  step "Purging all data"
  warn "this permanently deletes the database, the order images and the secret key."
  info "paths: $STATE_DB, $STATE_MEDIA, $STATE_UPLOADS, $ENV_FILE"

  if [ "$ASSUME_YES" -ne 1 ]; then
    printf '    to confirm, type %sDELETE%s: ' "$C_BOLD" "$C_RESET"
    read -r CONFIRM
    [ "$CONFIRM" = "DELETE" ] || die "cancelled; no data was deleted."
  fi

  info "taking a backup first…"
  if "${PROJECT_DIR}/scripts/backup.sh" --quiet; then
    ok "backup taken (before deletion)"
  else
    warn "the backup failed; continuing anyway."
  fi

  rm -f "$STATE_DB" "$ENV_FILE"
  rm -rf "$STATE_MEDIA" "$STATE_UPLOADS" "${PROJECT_DIR}/staticfiles"
  ok "all data deleted"
fi

cat <<EOF

${C_GREEN}${C_BOLD}Service removed.${C_RESET}
EOF

if [ "$PURGE_DATA" -eq 0 ]; then
  cat <<EOF
  Your data was left untouched:
    database : $STATE_DB
    images   : $STATE_MEDIA
  To install again:  sudo ./scripts/install.sh
EOF
fi
echo
