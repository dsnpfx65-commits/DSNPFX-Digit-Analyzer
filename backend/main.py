import asyncio
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
from backend.web_state import get_markets,get_opportunities,get_state,get_statistics,subscribe,unsubscribe
BASE_DIR=Path(__file__).resolve().parent; PROJECT_DIR=BASE_DIR.parent; PREDICTION_DB=BASE_DIR/"data"/"multi_market_learning.db"
def _build_revision():
    try:return subprocess.check_output(["git","rev-parse","--short","HEAD"],cwd=PROJECT_DIR,text=True,stderr=subprocess.DEVNULL).strip()
    except Exception:return "unknown"
BUILD_REVISION=_build_revision()
try:
 from backend.core import volatility_web_runner as _volatility_web_runner
 from backend.core.tick_precision_runtime import get_precision_runtime_snapshot,install_precision_runtime
 install_precision_runtime(_volatility_web_runner); precision_runtime_loaded=True
except Exception:
 precision_runtime_loaded=False
 def get_precision_runtime_snapshot():return {"totals":{},"tracked_markets":0,"healthy_markets":0,"stale_markets":0,"waiting_markets":0,"markets":[]}
try:
 from backend.core.strategy_forward_audit import get_strategy_comparison; strategy_forward_audit_loaded=True
except Exception:
 strategy_forward_audit_loaded=False
 def get_strategy_comparison(symbol=None):return []
try:
 from backend.core.adaptive_forward_ensemble import MODEL_KEYS as ADAPTIVE_MODEL_KEYS,get_adaptive_forward_ensemble; adaptive_forward_ensemble_loaded=True
except Exception:
 ADAPTIVE_MODEL_KEYS=(); adaptive_forward_ensemble_loaded=False
 def get_adaptive_forward_ensemble():return None
try:
 from backend.core.conditional_forward_discovery import get_conditional_forward_discovery; conditional_forward_discovery_loaded=True
except Exception:
 conditional_forward_discovery_loaded=False
 def get_conditional_forward_discovery():return None
try:
 from backend.core.v11_selective_demo_trader import get_v11_selective_demo_trader; v11_demo_loaded=True
except Exception:
 v11_demo_loaded=False
 def get_v11_selective_demo_trader():return None
try:from backend.core.all_volatility_web_runner import run_forever
except Exception:run_forever=None
try:from backend.core.proposal_quote_service import run_proposal_quote_loop
except Exception:run_proposal_quote_loop=None
@asynccontextmanager
async def lifespan(app):
 tasks=[]
 if run_forever is not None:tasks.append(asyncio.create_task(run_forever(),name="dsnpfx-market-runner"))
 if run_proposal_quote_loop is not None:tasks.append(asyncio.create_task(run_proposal_quote_loop(),name="dsnpfx-proposal-quotes"))
 try:yield
 finally:
  for task in tasks:task.cancel()
  if tasks:await asyncio.gather(*tasks,return_exceptions=True)
app=FastAPI(title="DSNPFX Market Insight AI",lifespan=lifespan); app.mount("/static",StaticFiles(directory=BASE_DIR/"static"),name="static")
@app.middleware("http")
async def disable_browser_cache(request,call_next):
 response=await call_next(request); response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"; response.headers["Pragma"]="no-cache"; response.headers["Expires"]="0"; response.headers["X-DSNPFX-Build"]=BUILD_REVISION; return response
@app.get("/")
async def dashboard():return FileResponse(BASE_DIR/"templates"/"index.html",headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","X-DSNPFX-Build":BUILD_REVISION})
@app.get("/api/health")
async def health():
 current=get_state(); precision=get_precision_runtime_snapshot(); return {"status":"ok","engine":"dsnpfx-market-insight","build_revision":BUILD_REVISION,"ui_generation":"V11_SELECTIVE_DEMO","market_count":current.get("market_count",0),"live_market_count":current.get("live_market_count",0),"scanner_loaded":run_forever is not None,"proposal_quotes_loaded":run_proposal_quote_loop is not None,"precision_runtime_loaded":precision_runtime_loaded,"strategy_forward_audit_loaded":strategy_forward_audit_loaded,"adaptive_forward_ensemble_loaded":adaptive_forward_ensemble_loaded,"conditional_forward_discovery_loaded":conditional_forward_discovery_loaded,"v11_demo_loaded":v11_demo_loaded,"precision_tracked_markets":precision.get("tracked_markets",0),"precision_healthy_markets":precision.get("healthy_markets",0),"precision_waiting_markets":precision.get("waiting_markets",0),"precision_stale_markets":precision.get("stale_markets",0)}
@app.get("/api/runtime-health")
async def runtime_health():
 precision=get_precision_runtime_snapshot(); current=get_state(); return {"build_revision":BUILD_REVISION,"precision_runtime_loaded":precision_runtime_loaded,"adaptive_forward_ensemble_loaded":adaptive_forward_ensemble_loaded,"conditional_forward_discovery_loaded":conditional_forward_discovery_loaded,"v11_demo_loaded":v11_demo_loaded,"market_count":current.get("market_count",0),"live_market_count":current.get("live_market_count",0),**precision}
@app.get("/api/strategy-comparison")
async def strategy_comparison(symbol:str|None=None):
 rows=get_strategy_comparison(symbol); return {"build_revision":BUILD_REVISION,"scope":"RESEARCH_ONLY","symbol":symbol or "ALL","count":len(rows),"strategies":rows}
@app.get("/api/adaptive-forward-results")
async def adaptive_forward_results(symbol:str|None=None):
 if not adaptive_forward_ensemble_loaded:return {"build_revision":BUILD_REVISION,"loaded":False,"scope":"RESEARCH_ONLY","symbol":symbol or "ALL","markets":[]}
 audit=get_adaptive_forward_ensemble()
 if audit is None:return {"build_revision":BUILD_REVISION,"loaded":False,"scope":"RESEARCH_ONLY","symbol":symbol or "ALL","markets":[]}
 snapshots=[audit.snapshot(symbol)] if symbol else [audit.snapshot(s) for s in sorted(get_markets().keys())]
 return {"build_revision":BUILD_REVISION,"loaded":True,"scope":"RESEARCH_ONLY_UNTIL_VERIFIED","baseline_pct":10.0,"required_resolved_per_model":100,"models":list(ADAPTIVE_MODEL_KEYS),"symbol":symbol or "ALL","market_count":len(snapshots),"markets":snapshots}
@app.get("/api/conditional-discovery")
async def conditional_discovery(symbol:str|None=None,limit:int=100):
 if not conditional_forward_discovery_loaded:return {"build_revision":BUILD_REVISION,"loaded":False,"scope":"RESEARCH_ONLY_CONDITIONAL_DISCOVERY","symbol":symbol or "ALL","leaders":[]}
 audit=get_conditional_forward_discovery()
 if audit is None:return {"build_revision":BUILD_REVISION,"loaded":False,"scope":"RESEARCH_ONLY_CONDITIONAL_DISCOVERY","symbol":symbol or "ALL","leaders":[]}
 payload=audit.summary(symbol=symbol); payload["leaders"]=payload.get("leaders",[])[:max(1,min(int(limit),1000))]; return {"build_revision":BUILD_REVISION,"loaded":True,**payload}
@app.get("/api/v11-demo-results")
async def v11_demo_results():
 trader=get_v11_selective_demo_trader() if v11_demo_loaded else None
 return {"build_revision":BUILD_REVISION,"loaded":trader is not None,**(trader.summary() if trader else {"mode":"UNAVAILABLE","live_buy_enabled":False,"resolved":0,"pending":0,"recent":[]})}
@app.get("/api/state")
async def state():return get_state()
@app.get("/api/markets")
async def markets():
 ranked=sorted(get_markets().values(),key=lambda x:(bool(x.get("is_premium")),float(x.get("edge_score",0) or 0)),reverse=True); return {"count":len(ranked),"markets":ranked}
@app.get("/api/opportunities")
async def opportunities():
 data=get_opportunities(); return {"count":len(data),"opportunities":data}
@app.get("/api/statistics")
async def statistics():return get_statistics()
@app.get("/api/predictions.csv")
async def prediction_history_csv():
 columns=["id","created_at","resolved_at","symbol","predicted","actual","result","selection_mode","confidence","calibrated_confidence","edge","edge_grade","regime","market_quality","source_epoch","source_quote","resolved_epoch","resolved_quote","rolling_accuracy","rolling_samples","rolling_lower_bound","rolling_upper_bound","statistically_above_baseline","model_predictions","model_weights","model_statistics"]
 output=io.StringIO(); writer=csv.DictWriter(output,fieldnames=columns,extrasaction="ignore"); writer.writeheader()
 if PREDICTION_DB.exists():
  connection=sqlite3.connect(str(PREDICTION_DB),timeout=10); connection.row_factory=sqlite3.Row
  try:
   available={row[1] for row in connection.execute("PRAGMA table_info(predictions)").fetchall()}; selected=[c for c in columns if c in available]
   if selected:
    for row in connection.execute(f"SELECT {', '.join(selected)} FROM predictions ORDER BY id ASC").fetchall():
     payload={c:row[c] for c in selected}
     for name in ("model_predictions","model_weights","model_statistics"):
      value=payload.get(name)
      if value is not None:
       try:payload[name]=json.dumps(json.loads(value),sort_keys=True)
       except Exception:payload[name]=str(value)
     writer.writerow(payload)
  finally:connection.close()
 return Response(content=output.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=dsnpfx_prediction_history.csv"})
@app.websocket("/ws")
async def websocket_endpoint(websocket:WebSocket):
 await websocket.accept(); queue=subscribe()
 try:
  await websocket.send_json({**get_state(),"markets":get_markets(),"opportunities":get_opportunities(),"statistics":get_statistics()})
  while True:
   update=await queue.get()
   try:await websocket.send_json(update)
   except (WebSocketDisconnect,RuntimeError,ConnectionError):break
 except WebSocketDisconnect:pass
 finally:unsubscribe(queue)
