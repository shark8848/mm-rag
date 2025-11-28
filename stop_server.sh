#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUN_DIR="$ROOT_DIR/.run"
STOP_CELERY=${STOP_CELERY:-true}
STOP_FLOWER=${STOP_FLOWER:-true}
SERVICES=($@)
if [[ ${#SERVICES[@]} -eq 0 ]]; then
  SERVICES=(all)
fi

STOP_FASTAPI=0
STOP_GRADIO=0
SELECT_CELERY=0
STOP_FLOWER_FLAG=0
for svc in "${SERVICES[@]}"; do
  case "$svc" in
    all)
      STOP_FASTAPI=1
      STOP_GRADIO=1
      SELECT_CELERY=1
      STOP_FLOWER_FLAG=1
      ;;
    api|uvicorn|fastapi)
      STOP_FASTAPI=1
      ;;
    gradio|ui)
      STOP_GRADIO=1
      ;;
    celery|workers)
      SELECT_CELERY=1
      ;;
    flower)
      STOP_FLOWER_FLAG=1
      ;;
    *)
      echo "[ERROR] Unknown service '$svc'. Choose from all|uvicorn|gradio|celery|flower." >&2
      exit 1
      ;;
  esac
done

STOP_CELERY_ENABLED=0
if [[ "$STOP_CELERY" == "true" && $SELECT_CELERY -eq 1 ]]; then
  STOP_CELERY_ENABLED=1
fi

STOP_FLOWER_ENABLED=0
if [[ "$STOP_FLOWER" == "true" && $STOP_FLOWER_FLAG -eq 1 ]]; then
  STOP_FLOWER_ENABLED=1
fi

PIDS=()
if [[ $STOP_FASTAPI -eq 1 ]]; then
  PIDS+=(uvicorn)
fi
if [[ $STOP_GRADIO -eq 1 ]]; then
  PIDS+=(gradio)
fi
if [[ $STOP_CELERY_ENABLED -eq 1 ]]; then
  PIDS+=(celery_cpu celery_io)
fi
if [[ $STOP_FLOWER_ENABLED -eq 1 ]]; then
  PIDS+=(flower)
fi

stop_pid() {
  local name=$1
  local pid_file="$RUN_DIR/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    return
  fi
  local pid
  pid=$(cat "$pid_file") || true
  if [[ -n "${pid:-}" ]]; then
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "Stopping $name (PID $pid)..."
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" 2>/dev/null || true
    else
      echo "$name process $pid is not running. Cleaning up PID file."
    fi
  fi
  rm -f "$pid_file"
}

if [[ -d "$RUN_DIR" ]]; then
  for name in "${PIDS[@]}"; do
    stop_pid "$name"
  done
fi

if [[ $STOP_FASTAPI -eq 1 ]]; then
  # As a fallback, ensure the FastAPI port is free.
  fuser -k 8000/tcp >/dev/null 2>&1 || true
fi

echo "Services stopped."
