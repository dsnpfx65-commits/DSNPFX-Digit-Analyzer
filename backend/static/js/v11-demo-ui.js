(() => {
  "use strict";
  const POLL_MS = 5000;
  const esc = (v) => String(v ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const num = (v, d=2) => Number.isFinite(Number(v)) ? Number(v).toFixed(d) : "--";
  function ensureStyles(){
    if(document.getElementById("v11-demo-style")) return;
    const s=document.createElement("style"); s.id="v11-demo-style"; s.textContent=`
      .v11-demo-panel{margin-top:18px}.v11-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
      .v11-grid>div{padding:12px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.025)}
      .v11-grid span{display:block;font-size:10px;opacity:.62;text-transform:uppercase;letter-spacing:.06em}.v11-grid strong{display:block;margin-top:5px;font-size:17px}
      .v11-table-wrap{overflow-x:auto}.v11-table{width:100%;border-collapse:collapse;min-width:900px}.v11-table th,.v11-table td{padding:9px 10px;border-top:1px solid rgba(255,255,255,.07);font-size:12px;text-align:left}
      .v11-table th{font-size:10px;opacity:.6;text-transform:uppercase}.v11-note{font-size:12px;opacity:.7;line-height:1.5;margin-top:12px}
    `; document.head.appendChild(s);
  }
  function ensurePanel(){
    const evidence=document.getElementById("tab-evidence"); if(!evidence) return null;
    let panel=document.getElementById("v11DemoPanel"); if(panel) return panel;
    panel=document.createElement("article"); panel.id="v11DemoPanel"; panel.className="panel v11-demo-panel";
    panel.innerHTML=`<div class="panel-heading"><div><p class="eyebrow">V11 Selective Trader</p><h2>Demo / Paper P&L</h2></div><span class="watch-badge">LIVE BUY OFF</span></div>
    <div class="v11-grid"><div><span>Resolved</span><strong data-v11="resolved">0</strong></div><div><span>Wins / Losses</span><strong data-v11="wl">0 / 0</strong></div><div><span>Accuracy</span><strong data-v11="acc">0.00%</strong></div><div><span>P&L Units</span><strong data-v11="pnl">0.00</strong></div><div><span>ROI</span><strong data-v11="roi">0.00%</strong></div><div><span>Max Drawdown</span><strong data-v11="dd">0.00</strong></div><div><span>Max Loss Streak</span><strong data-v11="ls">0</strong></div><div><span>Pending</span><strong data-v11="pending">0</strong></div></div>
    <div class="v11-table-wrap"><table class="v11-table"><thead><tr><th>Time</th><th>Market</th><th>Model</th><th>Condition</th><th>Digit</th><th>Result</th><th>P&L</th><th>Break-even</th></tr></thead><tbody data-v11="body"><tr><td colspan="8">Waiting for selective demo trades...</td></tr></tbody></table></div>
    <p class="v11-note">V11 does not buy contracts. It only records selective setups committed before settlement and scores them using the live DIGITMATCH economics. Real-money execution remains disabled.</p>`;
    evidence.prepend(panel); return panel;
  }
  function render(data){
    const p=ensurePanel(); if(!p) return;
    p.querySelector('[data-v11="resolved"]').textContent=String(data.resolved||0);
    p.querySelector('[data-v11="wl"]').textContent=`${data.wins||0} / ${data.losses||0}`;
    p.querySelector('[data-v11="acc"]').textContent=`${num(data.accuracy_pct)}%`;
    p.querySelector('[data-v11="pnl"]').textContent=num(data.pnl_units,4);
    p.querySelector('[data-v11="roi"]').textContent=`${num(data.roi_pct_on_unit_stakes)}%`;
    p.querySelector('[data-v11="dd"]').textContent=num(data.max_drawdown_units,4);
    p.querySelector('[data-v11="ls"]').textContent=String(data.max_consecutive_losses||0);
    p.querySelector('[data-v11="pending"]').textContent=String(data.pending||0);
    const rows=Array.isArray(data.recent)?data.recent:[];
    p.querySelector('[data-v11="body"]').innerHTML=rows.length?rows.map(r=>`<tr><td>${esc(r.created_at||"")}</td><td>${esc(r.symbol)}</td><td>${esc(r.model)}</td><td>${esc(`${r.condition_family}: ${r.condition_value}`)}</td><td>${esc(r.prediction)}</td><td>${esc(r.result||"PENDING")}</td><td>${r.pnl_units==null?"--":num(r.pnl_units,4)}</td><td>${num(r.break_even_probability_pct)}%</td></tr>`).join(""):'<tr><td colspan="8">Waiting for selective demo trades...</td></tr>';
  }
  async function refresh(){
    try{const r=await fetch("/api/v11-demo-results",{cache:"no-store"}); if(!r.ok) throw new Error(`HTTP ${r.status}`); render(await r.json());}
    catch(e){const p=ensurePanel(); if(p) p.querySelector('[data-v11="body"]').innerHTML=`<tr><td colspan="8">V11 results unavailable: ${esc(e.message||e)}</td></tr>`;}
  }
  document.addEventListener("DOMContentLoaded",()=>{ensureStyles();ensurePanel();refresh();});
  setTimeout(()=>{ensureStyles();ensurePanel();refresh();},0); setInterval(refresh,POLL_MS);
})();
