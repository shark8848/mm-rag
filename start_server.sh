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
FLOWER_PORT=${FLOWER_PORT:-5555}
START_FLOWER=${START_FLOWER:-true}

SERVICES=($@)
if [[ ${#SERVICES[@]} -eq 0 ]]; then
  SERVICES=(all)
fi

START_FASTAPI=0
START_GRADIO=0
SELECT_CELERY=0
START_FLOWER_FLAG=0
for svc in "${SERVICES[@]}"; do
  case "$svc" in
    all)
      START_FASTAPI=1
      START_GRADIO=1
      SELECT_CELERY=1
      START_FLOWER_FLAG=1
      ;;
    api|uvicorn|fastapi)
      START_FASTAPI=1
      ;;
    gradio|ui)
      START_GRADIO=1
      ;;
    celery|workers)
      SELECT_CELERY=1
      ;;
    flower)
      START_FLOWER_FLAG=1
      ;;
    *)
      echo "[ERROR] Unknown service '$svc'. Choose from all|uvicorn|gradio|celery." >&2
      exit 1
      ;;
  esac
done

START_CELERY_ENABLED=0
if [[ "$START_CELERY" == "true" && $SELECT_CELERY -eq 1 ]]; then
  START_CELERY_ENABLED=1
fi

START_FLOWER_ENABLED=0
if [[ "$START_FLOWER" == "true" && $START_FLOWER_FLAG -eq 1 ]]; then
  START_FLOWER_ENABLED=1
fi

if [[ $START_FASTAPI -eq 1 && ! -x "$VENV_BIN/uvicorn" ]]; then
  echo "[ERROR] Could not find .venv/bin/uvicorn. Please create the virtual environment and install dependencies." >&2
  exit 1
fi

if [[ ($START_CELERY_ENABLED -eq 1 || $START_FLOWER_ENABLED -eq 1) && ! -x "$VENV_BIN/celery" ]]; then
  echo "[ERROR] Celery/Flower requested but .venv/bin/celery not found. Install dependencies or disable START_CELERY/START_FLOWER." >&2
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
  "$ROOT_DIR/stop_server.sh" "${SERVICES[@]}" || true
fi

# Ensure FastAPI port is free before relaunching.
if [[ $START_FASTAPI -eq 1 ]]; then
  fuser -k "${UVICORN_PORT}/tcp" >/dev/null 2>&1 || true
fi

UVICORN_LOG="$LOG_DIR/uvicorn.log"
GRADIO_LOG="$LOG_DIR/gradio.log"
CELERY_CPU_LOG="$LOG_DIR/celery_cpu.log"
CELERY_IO_LOG="$LOG_DIR/celery_io.log"
FLOWER_LOG="$LOG_DIR/flower.log"

# Start FastAPI (Uvicorn) in the background with log redirection.
if [[ $START_FASTAPI -eq 1 ]]; then
  ("$VENV_BIN/uvicorn" main:app --host 0.0.0.0 --port "$UVICORN_PORT" >"$UVICORN_LOG" 2>&1 & echo $! >"$RUN_DIR/uvicorn.pid")
  echo "FastAPI server started on port ${UVICORN_PORT}. Logs: $UVICORN_LOG"

  if ! wait_for_http "FastAPI" "http://127.0.0.1:${UVICORN_PORT}/health"; then
    "$ROOT_DIR/stop_server.sh" "${SERVICES[@]}" || true
    exit 1
  fi
fi

# Start Gradio UI in the background.
if [[ $START_GRADIO -eq 1 ]]; then
  ("$VENV_BIN/python" ui/gradio_app.py --server.port "$GRADIO_PORT" --server.name 0.0.0.0 >"$GRADIO_LOG" 2>&1 & echo $! >"$RUN_DIR/gradio.pid")
  echo "Gradio UI started on port ${GRADIO_PORT}. Logs: $GRADIO_LOG"

  if ! wait_for_http "Gradio" "http://127.0.0.1:${GRADIO_PORT}"; then
    "$ROOT_DIR/stop_server.sh" "${SERVICES[@]}" || true
    exit 1
  fi
fi

if [[ $START_CELERY_ENABLED -eq 1 ]]; then
  ("$VENV_BIN/celery" -A app.celery_app worker -Q "$CELERY_CPU_QUEUE" -n "$CELERY_CPU_NAME" -l info >"$CELERY_CPU_LOG" 2>&1 & echo $! >"$RUN_DIR/celery_cpu.pid")
  echo "Celery CPU worker started on queue ${CELERY_CPU_QUEUE}. Logs: $CELERY_CPU_LOG"

  ("$VENV_BIN/celery" -A app.celery_app worker -Q "$CELERY_IO_QUEUE" -n "$CELERY_IO_NAME" -l info >"$CELERY_IO_LOG" 2>&1 & echo $! >"$RUN_DIR/celery_io.pid")
  echo "Celery IO worker started on queue ${CELERY_IO_QUEUE}. Logs: $CELERY_IO_LOG"
fi

if [[ $START_FLOWER_ENABLED -eq 1 ]]; then
  ("$VENV_BIN/celery" -A app.celery_app flower --address 0.0.0.0 --port "$FLOWER_PORT" >"$FLOWER_LOG" 2>&1 & echo $! >"$RUN_DIR/flower.pid")
  echo "Flower dashboard started on port ${FLOWER_PORT}. Logs: $FLOWER_LOG"

  if ! wait_for_http "Flower" "http://127.0.0.1:${FLOWER_PORT}"; then
    "$ROOT_DIR/stop_server.sh" "${SERVICES[@]}" || true
    exit 1
  fi
fi
