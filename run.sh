#!/usr/bin/env bash
#
# Start the Photo Frame 3D Django server.
#
#   ./run.sh              -> http://0.0.0.0:8080
#   HOST=127.0.0.1 PORT=9000 ./run.sh
#
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
VENV_DIR="${VENV_DIR:-.venv}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Creating virtual environment in $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r requirements.txt
fi

"$VENV_DIR/bin/python" manage.py migrate --noinput

# With PHOTO_FRAME_DEBUG=0 the dev server stops serving /static by itself, so
# ask it to keep doing that explicitly.
EXTRA=()
case "${PHOTO_FRAME_DEBUG:-1}" in
  0|false|False|no|off) EXTRA+=(--insecure) ;;
esac

echo "Serving Photo Frame 3D on http://$HOST:$PORT"
exec "$VENV_DIR/bin/python" manage.py runserver "${EXTRA[@]}" "$HOST:$PORT"
