import os
# DSNPFX AI Digit Analyzer Configuration

APP_NAME = "DSNPFX AI Digit Analyzer"
VERSION = "0.1.0"

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3"

APP_ID = ""
API_TOKEN = os.getenv("DERIV_API_TOKEN", "").strip()

