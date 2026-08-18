#!/usr/bin/env bash
#
# Photo Frame 3D — create or promote a super admin.
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
Usage: ./scripts/create-admin.sh [options]

  --phone <09…>          the admin's mobile number
  --email <a@b.com>      email address
  --name  "Full Name"    first and last name
  --generate-password    generate a random password and print it
  --password <pass>      use this password (it stays in your shell history)
  --noinput              never ask anything interactively

With no options, the details are asked interactively.
USAGE
  exit 0
fi

[ -x "$PYTHON_BIN" ] || die "virtualenv not found. Run this first:  sudo ./scripts/install.sh"

cd "$PROJECT_DIR"
exec "$PYTHON_BIN" manage.py create_admin "$@"
