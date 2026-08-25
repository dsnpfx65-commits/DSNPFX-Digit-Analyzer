#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/dsnpfx-dashboard.pid"
LOG_FILE="/tmp/dsnpfx-dashboard.log"

health_ok() {
  python - <<'PY'
import json
import urllib.request

try:
    with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
        payload = json.loads(response.read().decode('utf-8'))
except Exception:
    raise SystemExit(1)

raise SystemExit(0 if payload.get('status') == 'ok' else 1)
PY
}

# A healthy already-running dashboard should be left alone.
if health_ok; then
  echo "DSNPFX Market Insight is already healthy on port 8000"
  exit 0
fi

# If the old parent process exists but the HTTP service is unhealthy, stop it
# before starting a fresh server. This avoids a stale PID making Codespaces
# believe the dashboard is running when the browser can no longer reach it.
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 "$PID" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
  fi
fi
rm -f "$PID_FILE"

# Run a single stable Uvicorn process. Codespaces restarts this script on each
# container start, so development reload mode is unnecessary and less stable
# for a long-running live tick scanner.
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 >"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

for _ in $(seq 1 45); do
  if health_ok; then
    echo "DSNPFX Market Insight is running on port 8000"
    exit 0
  fi

  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "DSNPFX dashboard did not start. Recent log output:"
tail -n 100 "$LOG_FILE" || true
rm -f "$PID_FILE"
exit 1
