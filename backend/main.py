import asyncio
import contextlib
import csv
import io
import json
import sqlite3
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.web_state import (
    get_markets,
    get_opportunities,
    get_state,
    get_statistics,
    subscribe,
    unsubscribe,
)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
PREDICTION_DB = BASE_DIR / "data" / "multi_market_learning.db"


def _build_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


BUILD_REVISION = _build_revision()

try:
    from backend.core import volatility_web_runner as _volatility_web_runner
    from backend.core.tick_precision_runtime import (
        get_precision_runtime_snapshot,
        install_precision_runtime,
    )

    install_precision_runtime(_volatility_web_runner)
    precision_runtime_loaded = True
except Exception:
    precision_runtime_loaded = False

    def get_precision_runtime_snapshot():
        return {
            "totals": {},
            "tracked_markets": 0,
            "healthy_markets": 0,
            "stale_markets": 0,
            "waiting_markets": 0,
            "markets": [],
        }

try:
    from backend.core.strategy_forward_audit import get_strategy_comparison
    strategy_forward_audit_loaded = True
except Exception:
    strategy_forward_audit_loaded = False

    def get_strategy_comparison(symbol=None):
        return []

try:
    from backend.core.all_volatility_web_runner import run_forever
except Exception:
    run_forever = None

try:
    from backend.core.proposal_quote_service import run_proposal_quote_loop
except Exception:
    run_proposal_quote_loop = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = []
    if run_forever is not None:
        tasks.append(asyncio.create_task(run_forever(), name="dsnpfx-market-runner"))
    if run_proposal_quote_loop is not None:
        tasks.append(
            asyncio.create_task(
                run_proposal_quote_loop(),
                name="dsnpfx-proposal-quotes",
            )
        )
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="DSNPFX Market Insight AI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def disable_browser_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-DSNPFX-Build"] = BUILD_REVISION
    return response


@app.get("/")
async def dashboard():
    return FileResponse(
        BASE_DIR / "templates" / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-DSNPFX-Build": BUILD_REVISION,
        },
    )


@app.get("/api/health")
async def health():
    current = get_state()
    precision = get_precision_runtime_snapshot()
    return {
        "status": "ok",
        "engine": "dsnpfx-market-insight",
        "build_revision": BUILD_REVISION,
        "ui_generation": "V9_RESEARCH_LAYER",
        "market_count": current.get("market_count", 0),
        "live_market_count": current.get("live_market_count", 0),
        "scanner_loaded": run_forever is not None,
        "proposal_quotes_loaded": run_proposal_quote_loop is not None,
        "precision_runtime_loaded": precision_runtime_loaded,
        "strategy_forward_audit_loaded": strategy_forward_audit_loaded,
        "precision_tracked_markets": precision.get("tracked_markets", 0),
        "precision_healthy_markets": precision.get("healthy_markets", 0),
        "precision_waiting_markets": precision.get("waiting_markets", 0),
        "precision_stale_markets": precision.get("stale_markets", 0),
        "metadata_precision_ticks": (precision.get("totals") or {}).get(
            "metadata_precision",
            0,
        ),
        "missing_precision_ticks": (precision.get("totals") or {}).get(
            "missing_precision",
            0,
        ),
    }


@app.get("/api/runtime-health")
async def runtime_health():
    precision = get_precision_runtime_snapshot()
    current = get_state()
    return {
        "build_revision": BUILD_REVISION,
        "precision_runtime_loaded": precision_runtime_loaded,
        "market_count": current.get("market_count", 0),
        "live_market_count": current.get("live_market_count", 0),
        **precision,
    }


@app.get("/api/strategy-comparison")
async def strategy_comparison(symbol: str | None = None):
    """Read-only prospective strategy leaderboard.

    Rankings use resolved next-tick outcomes recorded before settlement. No
    strategy is marked EVIDENCE_EDGE until it has at least 100 resolved samples
    and its 95% Wilson lower bound clears both its natural contract baseline and
    the average live Deriv break-even captured for priced samples.
    """
    rows = get_strategy_comparison(symbol)
    return {
        "build_revision": BUILD_REVISION,
        "scope": "RESEARCH_ONLY",
        "symbol": symbol or "ALL",
        "count": len(rows),
        "strategies": rows,
    }


@app.get("/api/state")
async def state():
    return get_state()


@app.get("/api/markets")
async def markets():
    current = get_markets()
    ranked = sorted(
        current.values(),
        key=lambda item: (
            bool(item.get("is_premium")),
            float(item.get("edge_score", 0) or 0),
        ),
        reverse=True,
    )
    return {"count": len(ranked), "markets": ranked}


@app.get("/api/opportunities")
async def opportunities():
    data = get_opportunities()
    return {"count": len(data), "opportunities": data}


@app.get("/api/statistics")
async def statistics():
    return get_statistics()


@app.get("/api/predictions.csv")
async def prediction_history_csv():
    columns = [
        "id",
        "created_at",
        "resolved_at",
        "symbol",
        "predicted",
        "actual",
        "result",
        "selection_mode",
        "confidence",
        "calibrated_confidence",
        "edge",
        "edge_grade",
        "regime",
        "market_quality",
        "source_epoch",
        "source_quote",
        "resolved_epoch",
        "resolved_quote",
        "rolling_accuracy",
        "rolling_samples",
        "rolling_lower_bound",
        "rolling_upper_bound",
        "statistically_above_baseline",
        "model_predictions",
        "model_weights",
        "model_statistics",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    if PREDICTION_DB.exists():
        connection = sqlite3.connect(str(PREDICTION_DB), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            available = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(predictions)"
                ).fetchall()
            }
            selected = [column for column in columns if column in available]
            if selected:
                rows = connection.execute(
                    f"SELECT {', '.join(selected)} FROM predictions ORDER BY id ASC"
                ).fetchall()
                for row in rows:
                    payload = {column: row[column] for column in selected}
                    for name in (
                        "model_predictions",
                        "model_weights",
                        "model_statistics",
                    ):
                        value = payload.get(name)
                        if value is None:
                            continue
                        try:
                            payload[name] = json.dumps(json.loads(value), sort_keys=True)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            payload[name] = str(value)
                    writer.writerow(payload)
        finally:
            connection.close()

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=dsnpfx_prediction_history.csv"
        },
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    queue = subscribe()
    try:
        await websocket.send_json({
            **get_state(),
            "markets": get_markets(),
            "opportunities": get_opportunities(),
            "statistics": get_statistics(),
        })
        while True:
            update = await queue.get()
            try:
                await websocket.send_json(update)
            except (WebSocketDisconnect, RuntimeError, ConnectionError):
                break
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(queue)
