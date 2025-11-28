#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VENV_BIN="$ROOT_DIR/.venv/bin"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/data/logs"
UVICORN_PORT=${UVICORN_PORT:-8000}
GRADIO_PORT=${GRADIO_PORT:-7860}
HEALTH_RETRIES=${HEALTH_RETRIES:-30}

if [[ ! -x "$VENV_BIN/uvicorn" ]]; then
  echo "[ERROR] Could not find .venv/bin/uvicorn. Please create the virtual environment and install dependencies." >&2
  exit 1
fi

mkdir -p "$RUN_DIR" "$LOG_DIR"

# Simple HTTP readiness probe using curl.
wait_for_http() {
  local name=$1
  local url=$2
  local retries=${3:-$HEALTH_RETRIES}

  for ((attempt = 1; attempt <= retries; attempt++)); do
    if curl -sSf "$url" >/dev/null 2>&1; then
      echo "$name is healthy at $url (attempt $attempt)"
      return 0
    fi
    sleep 1
  done

  echo "[ERROR] $name did not become healthy at $url within ${retries}s" >&2
  return 1
}

# Stop existing services gracefully before starting new ones.
if [[ -x "$ROOT_DIR/stop_server.sh" ]]; then
  "$ROOT_DIR/stop_server.sh" || true
fi

# Ensure FastAPI port is free before relaunching.
fuser -k "${UVICORN_PORT}/tcp" >/dev/null 2>&1 || true

UVICORN_LOG="$LOG_DIR/uvicorn.log"
GRADIO_LOG="$LOG_DIR/gradio.log"

# Start FastAPI (Uvicorn) in the background with log redirection.
("$VENV_BIN/uvicorn" main:app --host 0.0.0.0 --port "$UVICORN_PORT" >"$UVICORN_LOG" 2>&1 & echo $! >"$RUN_DIR/uvicorn.pid")
echo "FastAPI server started on port ${UVICORN_PORT}. Logs: $UVICORN_LOG"

if ! wait_for_http "FastAPI" "http://127.0.0.1:${UVICORN_PORT}/health"; then
  "$ROOT_DIR/stop_server.sh" || true
  exit 1
}

# Start Gradio UI in the background.
("$VENV_BIN/python" ui/gradio_app.py --server.port "$GRADIO_PORT" --server.name 0.0.0.0 >"$GRADIO_LOG" 2>&1 & echo $! >"$RUN_DIR/gradio.pid")
echo "Gradio UI started on port ${GRADIO_PORT}. Logs: $GRADIO_LOG"

if ! wait_for_http "Gradio" "http://127.0.0.1:${GRADIO_PORT}"; then
  "$ROOT_DIR/stop_server.sh" || true
  exit 1
}
