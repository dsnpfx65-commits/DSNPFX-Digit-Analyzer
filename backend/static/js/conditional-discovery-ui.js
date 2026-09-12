(() => {
  "use strict";

  const POLL_MS = 5000;

  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const pct = (value) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(2)}%` : "--";
  const pp = (value) => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(2)} pp` : "--";
  const model = (key) => ({frequency:"Frequency",markov:"Markov",sequence:"Sequence",probability_best:"Probability Best",hot_1000:"HOT 1000",cold_1000:"COLD 1000"}[key] || key || "--");

  function addStyles() {
    if (document.getElementById("conditionalDiscoveryStyle")) return;
    const style = document.createElement("style");
    style.id = "conditionalDiscoveryStyle";
    style.textContent = `
      .conditional-panel{margin-top:18px}.conditional-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:14px 0}
      .conditional-summary>div{padding:12px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.025)}
      .conditional-summary span{display:block;font-size:11px;opacity:.62;text-transform:uppercase;letter-spacing:.06em}.conditional-summary strong{display:block;margin-top:5px;font-size:17px}
      .conditional-table-wrap{overflow-x:auto}.conditional-table{width:100%;border-collapse:collapse;min-width:1120px}
      .conditional-table th,.conditional-table td{padding:10px 11px;text-align:left;border-top:1px solid rgba(255,255,255,.07);font-size:12px;white-space:nowrap}
      .conditional-table th{font-size:10px;opacity:.62;text-transform:uppercase;letter-spacing:.05em}.conditional-edge{font-weight:800}.conditional-note{font-size:12px;opacity:.68;line-height:1.5;margin-top:12px}
    `;
    document.head.appendChild(style);
  }

  function ensurePanel() {
    const evidence = document.getElementById("tab-evidence");
    if (!evidence) return null;
    let panel = document.getElementById("conditionalDiscoveryPanel");
    if (panel) return panel;
    panel = document.createElement("article");
    panel.id = "conditionalDiscoveryPanel";
    panel.className = "panel conditional-panel";
    panel.innerHTML = `
      <div class="panel-heading"><div><p class="eyebrow">Prospective Holdout Research</p><h2>Conditional Edge Discovery</h2></div><span class="watch-badge">Discovery → Validation</span></div>
      <div class="conditional-summary">
        <div><span>Conditions Tested</span><strong data-cond="tested">0</strong></div>
        <div><span>Discovery Promising</span><strong data-cond="promising">0</strong></div>
        <div><span>Validation Edges</span><strong data-cond="edges">0</strong></div>
        <div><span>Last Refresh</span><strong data-cond="updated">--</strong></div>
      </div>
      <div class="conditional-table-wrap"><table class="conditional-table"><thead><tr>
        <th>Market</th><th>Model</th><th>Condition</th><th>Discovery N</th><th>Discovery Acc</th><th>Discovery L95</th><th>Validation N</th><th>Validation Acc</th><th>Validation L95</th><th>Avg B/E</th><th>Conservative Edge</th><th>Status</th>
      </tr></thead><tbody data-cond="body"><tr><td colspan="12">Collecting conditional forward evidence...</td></tr></tbody></table></div>
      <p class="conditional-note">Research only. Conditions are fixed before settlement and split prospectively into discovery and validation. A condition is not an edge unless its independent validation 95% lower bound clears the recorded live DIGITMATCH break-even.</p>`;
    const leaderboard = document.getElementById("modelAccuracyLeaderboard");
    if (leaderboard) evidence.insertBefore(panel, leaderboard); else evidence.appendChild(panel);
    return panel;
  }

  function render(payload) {
    const panel = ensurePanel(); if (!panel) return;
    const rows = Array.isArray(payload?.leaders) ? payload.leaders : [];
    panel.querySelector('[data-cond="tested"]').textContent = String(payload?.conditions_tested ?? rows.length);
    panel.querySelector('[data-cond="promising"]').textContent = String(payload?.discovery_promising ?? 0);
    panel.querySelector('[data-cond="edges"]').textContent = String(payload?.validation_edges ?? 0);
    panel.querySelector('[data-cond="updated"]').textContent = new Date().toLocaleTimeString();
    const body = panel.querySelector('[data-cond="body"]');
    if (!rows.length) { body.innerHTML = '<tr><td colspan="12">No resolved conditional evidence yet.</td></tr>'; return; }
    body.innerHTML = rows.slice(0, 100).map((row) => {
      const d = row.discovery || {}, v = row.validation || {};
      const condition = `${row.condition_family || "--"}: ${row.condition_value || "--"}`;
      return `<tr>
        <td>${esc(row.symbol)}</td><td>${esc(model(row.model))}</td><td>${esc(condition)}</td>
        <td>${Number(d.resolved || 0)}</td><td>${pct(d.accuracy_pct)}</td><td>${pct(d.lower_95_pct)}</td>
        <td>${Number(v.resolved || 0)}</td><td>${pct(v.accuracy_pct)}</td><td>${pct(v.lower_95_pct)}</td>
        <td>${pct(v.average_break_even_pct)}</td><td>${pp(v.conservative_edge_pp)}</td>
        <td class="${row.validation_economic_edge ? "conditional-edge" : ""}">${esc(row.status || "COLLECTING")}</td>
      </tr>`;
    }).join("");
  }

  async function refresh() {
    try {
      const response = await fetch("/api/conditional-discovery?limit=100", {cache:"no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      const panel = ensurePanel(); const body = panel?.querySelector('[data-cond="body"]');
      if (body) body.innerHTML = `<tr><td colspan="12">Conditional discovery unavailable: ${esc(error?.message || error)}</td></tr>`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => { addStyles(); ensurePanel(); refresh(); });
  setTimeout(() => { addStyles(); ensurePanel(); refresh(); }, 0);
  setInterval(refresh, POLL_MS);
})();
