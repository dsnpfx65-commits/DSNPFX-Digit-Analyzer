#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/dsnpfx-dashboard.pid"
LOG_FILE="/tmp/dsnpfx-dashboard.log"
COMMIT_FILE="/tmp/dsnpfx-dashboard.commit"
CURRENT_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

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

running_commit=""
if [ -f "$COMMIT_FILE" ]; then
  running_commit="$(cat "$COMMIT_FILE" 2>/dev/null || true)"
fi

# Leave the server alone only when it is healthy AND it was launched from the
# same git commit. After a pull, a healthy old process must be restarted so the
# browser actually serves the newly checked-out frontend/backend code.
if health_ok && [ -n "$running_commit" ] && [ "$running_commit" = "$CURRENT_COMMIT" ]; then
  echo "DSNPFX Market Insight is already healthy on port 8000 ($CURRENT_COMMIT)"
  exit 0
fi

if health_ok; then
  echo "DSNPFX Market Insight is healthy but serving an older checkout; restarting..."
fi

# Stop only the PID previously launched by this dashboard script.
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    for _ in $(seq 1 15); do
      if ! kill -0 "$PID" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
  fi
fi
rm -f "$PID_FILE" "$COMMIT_FILE"

# If port 8000 is still healthy after the recorded process was stopped, an old
# child/worker is still serving it. Stop only listeners on this dedicated
# Codespaces dashboard port; never use a broad pkill pattern.
if health_ok; then
  if command -v fuser >/dev/null 2>&1; then
    fuser -k 8000/tcp >/dev/null 2>&1 || true
    sleep 1
  fi
fi

# Run a single stable Uvicorn process. Codespaces restarts this script on each
# container start, so reload mode is unnecessary for normal operation.
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 >"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "$CURRENT_COMMIT" > "$COMMIT_FILE"

for _ in $(seq 1 45); do
  if health_ok; then
    echo "DSNPFX Market Insight is running on port 8000 ($CURRENT_COMMIT)"
    exit 0
  fi

  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "DSNPFX dashboard did not start. Recent log output:"
tail -n 100 "$LOG_FILE" || true
rm -f "$PID_FILE" "$COMMIT_FILE"
exit 1
