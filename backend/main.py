import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
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

try:
    from backend.core.all_volatility_web_runner import run_forever
except Exception:
    run_forever = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if run_forever is not None:
        task = asyncio.create_task(run_forever())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="DSNPFX Market Insight AI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def dashboard():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/api/health")
async def health():
    current = get_state()
    return {
        "status": "ok",
        "engine": "dsnpfx-market-insight",
        "market_count": current.get("market_count", 0),
        "live_market_count": current.get("live_market_count", 0),
        "scanner_loaded": run_forever is not None,
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
