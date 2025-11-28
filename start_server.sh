#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VENV_BIN="$ROOT_DIR/.venv/bin"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/data/logs"
UVICORN_PORT=${UVICORN_PORT:-8000}
GRADIO_PORT=${GRADIO_PORT:-7860}
HEALTH_RETRIES=${HEALTH_RETRIES:-30}
CELERY_CPU_QUEUE=${CELERY_CPU_QUEUE:-ingest_cpu}
CELERY_IO_QUEUE=${CELERY_IO_QUEUE:-ingest_io}
HOSTNAME_CMD=$(hostname 2>/dev/null || echo "localhost")
CELERY_CPU_NAME=${CELERY_CPU_NAME:-ingest_cpu@${HOSTNAME_CMD}}
CELERY_IO_NAME=${CELERY_IO_NAME:-ingest_io@${HOSTNAME_CMD}}
START_CELERY=${START_CELERY:-true}

if [[ ! -x "$VENV_BIN/uvicorn" ]]; then
  echo "[ERROR] Could not find .venv/bin/uvicorn. Please create the virtual environment and install dependencies." >&2
  exit 1
fi

if [[ "$START_CELERY" == "true" && ! -x "$VENV_BIN/celery" ]]; then
  echo "[ERROR] START_CELERY=true but .venv/bin/celery not found. Install dependencies or set START_CELERY=false." >&2
  exit 1
fi

mkdir -p "$RUN_DIR" "$LOG_DIR"

# Simple HTTP readiness probe using curl (POSIX-friendly for wider shell support).
wait_for_http() {
  name=$1
  url=$2
  retries=${3:-$HEALTH_RETRIES}

  attempt=1
  while [ "$attempt" -le "$retries" ]; do
    if curl -sSf "$url" >/dev/null 2>&1; then
      echo "$name is healthy at $url (attempt $attempt)"
      return 0
    fi
    attempt=$((attempt + 1))
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
CELERY_CPU_LOG="$LOG_DIR/celery_cpu.log"
CELERY_IO_LOG="$LOG_DIR/celery_io.log"

# Start FastAPI (Uvicorn) in the background with log redirection.
("$VENV_BIN/uvicorn" main:app --host 0.0.0.0 --port "$UVICORN_PORT" >"$UVICORN_LOG" 2>&1 & echo $! >"$RUN_DIR/uvicorn.pid")
echo "FastAPI server started on port ${UVICORN_PORT}. Logs: $UVICORN_LOG"

if ! wait_for_http "FastAPI" "http://127.0.0.1:${UVICORN_PORT}/health"; then
  "$ROOT_DIR/stop_server.sh" || true
  exit 1
fi

# Start Gradio UI in the background.
("$VENV_BIN/python" ui/gradio_app.py --server.port "$GRADIO_PORT" --server.name 0.0.0.0 >"$GRADIO_LOG" 2>&1 & echo $! >"$RUN_DIR/gradio.pid")
echo "Gradio UI started on port ${GRADIO_PORT}. Logs: $GRADIO_LOG"

if ! wait_for_http "Gradio" "http://127.0.0.1:${GRADIO_PORT}"; then
  "$ROOT_DIR/stop_server.sh" || true
  exit 1
fi

if [[ "$START_CELERY" == "true" ]]; then
  ("$VENV_BIN/celery" -A app.celery_app worker -Q "$CELERY_CPU_QUEUE" -n "$CELERY_CPU_NAME" -l info >"$CELERY_CPU_LOG" 2>&1 & echo $! >"$RUN_DIR/celery_cpu.pid")
  echo "Celery CPU worker started on queue ${CELERY_CPU_QUEUE}. Logs: $CELERY_CPU_LOG"

  ("$VENV_BIN/celery" -A app.celery_app worker -Q "$CELERY_IO_QUEUE" -n "$CELERY_IO_NAME" -l info >"$CELERY_IO_LOG" 2>&1 & echo $! >"$RUN_DIR/celery_io.pid")
  echo "Celery IO worker started on queue ${CELERY_IO_QUEUE}. Logs: $CELERY_IO_LOG"
fi
