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
Usage: sudo ./scripts/restore.sh <backup-file.zip> [options]

  --inspect        only show what is inside the backup, then exit
  --skip-env       keep the current .env (do not replace the secret key)
  --no-safety      skip the safety snapshot of the current state (not recommended)
  --yes            proceed without asking for confirmation
  -h, --help       this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --inspect) INSPECT=1; shift ;;
    --skip-env) SKIP_ENV=1; shift ;;
    --no-safety) NO_SAFETY=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option: $1  (see --help)" ;;
    *) ARCHIVE="$1"; shift ;;
  esac
done

[ -n "$ARCHIVE" ] || { usage; die "give the path to a backup file."; }
[ -f "$ARCHIVE" ] || die "file not found: $ARCHIVE"
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

PY="$PYTHON_BIN"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "python3 not found."

# --- inspect only ------------------------------------------------------------

if [ "$INSPECT" -eq 1 ]; then
  "$PY" "${PROJECT_DIR}/scripts/_restore.py" \
    --project-dir "$PROJECT_DIR" --archive "$ARCHIVE" --inspect
  exit 0
fi

require_root "$@"

step "Validating the backup file"
MANIFEST="$("$PY" "${PROJECT_DIR}/scripts/_restore.py" \
  --project-dir "$PROJECT_DIR" --archive "$ARCHIVE" --inspect)"

"$PY" - "$MANIFEST" <<'PY'
import json, sys
m = json.loads(sys.argv[1])
counts = m.get("counts") or {}
print(f"    created at : {m.get('created_at')}")
print(f"    source     : {m.get('hostname')}  ({m.get('source_project_dir')})")
print(f"    contents   : {counts.get('users')} users, "
      f"{counts.get('orders')} orders, {counts.get('color_profiles')} colour profiles")
print(f"    has .env   : {'yes' if m.get('includes_env') else 'no'}")
PY
ok "the backup file is valid"

if [ "$ASSUME_YES" -ne 1 ]; then
  warn "restoring replaces the current database and the order images."
  printf '    to continue, type %sRESTORE%s: ' "$C_BOLD" "$C_RESET"
  read -r CONFIRM
  [ "$CONFIRM" = "RESTORE" ] || die "cancelled; nothing was changed."
fi

# --- safety snapshot ---------------------------------------------------------

if [ "$NO_SAFETY" -eq 0 ]; then
  step "Safety snapshot of the current state"
  SAFETY="${PROJECT_DIR}/backups/pre-restore-$(date +%Y%m%d-%H%M%S).zip"
  if "${PROJECT_DIR}/scripts/backup.sh" --output "$SAFETY" --quiet >/dev/null; then
    ok "current state saved: $SAFETY"
  else
    warn "the safety snapshot failed."
    [ "$ASSUME_YES" -eq 1 ] || die "use --no-safety to continue without a safety snapshot."
  fi
fi

# --- stop, restore, start ----------------------------------------------------

WAS_RUNNING=0
if service_active; then
  WAS_RUNNING=1
  step "Stopping the service temporarily"
  systemctl stop "$SERVICE_NAME"
  ok "service stopped"
fi

step "Restoring the state"
RESTORE_ARGS=(--project-dir "$PROJECT_DIR" --archive "$ARCHIVE")
[ "$SKIP_ENV" -eq 1 ] && RESTORE_ARGS+=(--skip-env)

RESULT="$("$PY" "${PROJECT_DIR}/scripts/_restore.py" "${RESTORE_ARGS[@]}")"
ok "database and files restored"

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
ok "file ownership set to $RUN_AS"

# An older backup may predate newer migrations.
if [ -x "$PYTHON_BIN" ]; then
  step "Syncing the database schema"
  cd "$PROJECT_DIR"
  "$PYTHON_BIN" manage.py migrate --noinput
  ok "migrations applied"
else
  warn ".venv not found; migrations were not run. Run ./scripts/install.sh first."
fi

if [ "$WAS_RUNNING" -eq 1 ] || service_installed; then
  step "Starting the service again"
  systemctl start "$SERVICE_NAME"
  PORT="$(app_port)"
  if wait_for_http "http://127.0.0.1:${PORT}/" 40; then
    ok "the application is running with the restored state"
  else
    warn "the application did not respond; check the logs:  journalctl -u ${SERVICE_NAME} -n 50"
  fi
fi

echo
printf '%s%sRestore completed successfully.%s\n' "$C_GREEN" "$C_BOLD" "$C_RESET"
"$PY" - "$RESULT" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
counts = d.get("counts") or {}
print(f"    source   : {d['restored_from']}")
print(f"    date     : {d.get('created_at')}")
print(f"    contents : {counts.get('users')} users, {counts.get('orders')} orders")
PY
echo
