#!/bin/bash
# Auto-restart wrapper for Project Sunday worker
# Usage: bash apps/worker/run_worker.sh
cd "$(dirname "$0")"
while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting worker..."
  .venv/bin/python main.py
  EXIT_CODE=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Worker exited with code $EXIT_CODE. Restarting in 5 seconds..."
  sleep 5
done
