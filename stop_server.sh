#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUN_DIR="$ROOT_DIR/.run"
PIDS=(uvicorn gradio)

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

# As a fallback, ensure the FastAPI port is free.
fuser -k 8000/tcp >/dev/null 2>&1 || true

echo "Services stopped."
