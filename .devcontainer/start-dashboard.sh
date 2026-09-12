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

if health_ok && [ -n "$running_commit" ] && [ "$running_commit" = "$CURRENT_COMMIT" ]; then
  echo "DSNPFX Market Insight is already healthy on port 8000 ($CURRENT_COMMIT)"
  exit 0
fi

if health_ok; then
  echo "DSNPFX Market Insight is healthy but serving an older checkout; restarting..."
fi

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$PID" 2>/dev/null; then break; fi
      sleep 0.2
    done
  fi
fi
rm -f "$PID_FILE" "$COMMIT_FILE"

# Always clear any stale listener on the dedicated dashboard port before bind.
# This is intentionally scoped to TCP/8000 only; it never uses a broad pkill.
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp >/dev/null 2>&1 || true
else
  python - <<'PY'
import os, signal, subprocess
try:
    out = subprocess.check_output(["bash","-lc","lsof -ti tcp:8000 2>/dev/null || true"], text=True)
except Exception:
    out = ""
for item in out.split():
    try:
        os.kill(int(item), signal.SIGTERM)
    except Exception:
        pass
PY
fi

# Wait until the port is actually released before starting the new checkout.
for _ in $(seq 1 25); do
  python - <<'PY'
import socket
s=socket.socket(); s.settimeout(0.2)
try:
    s.connect(("127.0.0.1",8000))
except OSError:
    raise SystemExit(0)
else:
    raise SystemExit(1)
finally:
    s.close()
PY
  if [ $? -eq 0 ]; then break; fi
  sleep 0.2
done

nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 >"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "$CURRENT_COMMIT" > "$COMMIT_FILE"

for _ in $(seq 1 45); do
  if health_ok; then
    echo "DSNPFX Market Insight is running on port 8000 ($CURRENT_COMMIT)"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  sleep 1
done

echo "DSNPFX dashboard did not start. Recent log output:"
tail -n 100 "$LOG_FILE" || true
rm -f "$PID_FILE" "$COMMIT_FILE"
exit 1
