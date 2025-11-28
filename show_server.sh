#!/usr/bin/env bash
set -euo pipefail

# Displays the current status for each managed service without modifying state.

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/data/logs"

UVICORN_PORT=${UVICORN_PORT:-8000}
GRADIO_PORT=${GRADIO_PORT:-7860}
CELERY_CPU_QUEUE=${CELERY_CPU_QUEUE:-ingest_cpu}
CELERY_IO_QUEUE=${CELERY_IO_QUEUE:-ingest_io}
FLOWER_PORT=${FLOWER_PORT:-5555}

SERVICE_MATRIX=(
  "uvicorn|FastAPI API|${UVICORN_PORT}|${LOG_DIR}/uvicorn.log"
  "gradio|Gradio UI|${GRADIO_PORT}|${LOG_DIR}/gradio.log"
  "celery_cpu|Celery CPU (${CELERY_CPU_QUEUE})||${LOG_DIR}/celery_cpu.log"
  "celery_io|Celery IO (${CELERY_IO_QUEUE})||${LOG_DIR}/celery_io.log"
  "flower|Flower Dashboard|${FLOWER_PORT}|${LOG_DIR}/flower.log"
)

read_pid() {
  local file=$1
  if [[ -f "$file" ]]; then
    tr -d '\n' <"$file"
  fi
}

status_for() {
  local pid=$1
  if [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]]; then
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "running"
      return
    fi
    echo "stale"
    return
  fi
  echo "stopped"
}

printf "%-22s %-10s %-8s %-8s %s\n" "Service" "Status" "PID" "Port" "Log"
printf '%s\n' "--------------------------------------------------------------------------------"

for row in "${SERVICE_MATRIX[@]}"; do
  IFS='|' read -r key label port log <<<"$row"
  pid_file="$RUN_DIR/${key}.pid"
  pid=$(read_pid "$pid_file")
  status=$(status_for "$pid")
  display_pid=${pid:-"-"}
  [[ "$status" == "stale" ]] && display_pid="?"
  display_port=${port:-"-"}
  [[ ! -f "$pid_file" && "$status" == "stopped" ]] && status="idle"
  printf "%-22s %-10s %-8s %-8s %s\n" "$label" "$status" "$display_pid" "$display_port" "$log"
done
