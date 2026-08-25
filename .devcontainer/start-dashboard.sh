#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/dsnpfx-dashboard.pid"
LOG_FILE="/tmp/dsnpfx-dashboard.log"

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    exit 0
  fi
fi

nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload >"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

for _ in $(seq 1 30); do
  if python - <<'PY'
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1)
except Exception:
    raise SystemExit(1)
raise SystemExit(0)
PY
  then
    echo "DSNPFX Market Insight is running on port 8000 (auto-reload enabled)"
    exit 0
  fi
  sleep 1
done

echo "DSNPFX dashboard did not start. Recent log output:"
tail -n 80 "$LOG_FILE" || true
exit 1
