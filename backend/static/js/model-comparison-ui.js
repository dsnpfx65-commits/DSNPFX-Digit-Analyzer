(() => {
  "use strict";

  const dash = "--";

  function digit(value) {
    const n = Number(value);
    return Number.isInteger(n) && n >= 0 && n <= 9 ? String(n) : dash;
  }

  function metadata(market) {
    return market?.model_metadata && typeof market.model_metadata === "object"
      ? market.model_metadata
      : {};
  }

  function currentCandidates(market) {
    const meta = metadata(market);
    const probability = meta.probability_analysis || {};
    const hot = meta.hot_1000_continuation || {};
    const cold = meta.cold_reversion || {};
    const coldWindows = cold.windows || {};
    const cold1000 = coldWindows[1000] || coldWindows["1000"] || {};
    const models = market?.model_predictions || {};

    return [
      { key: "v9", label: "V9 Main", value: digit(market?.candidate_prediction) },
      { key: "proposal", label: "Probability Best", value: digit(probability?.best_match_digit) },
      { key: "markov", label: "Markov", value: digit(models?.markov) },
      { key: "sequence", label: "N-gram", value: digit(models?.sequence) },
      { key: "hot1000", label: "HOT 1000", value: digit(hot?.candidate) },
      { key: "cold1000", label: "COLD 1000", value: digit(cold1000?.candidate ?? cold?.primary_candidate) },
    ];
  }

  function agreementSummary(candidates) {
    const v9 = candidates.find((item) => item.key === "v9")?.value;
    const comparable = candidates.filter((item) => item.value !== dash);
    if (!v9 || v9 === dash || comparable.length <= 1) {
      return { text: "WAITING FOR MODELS", agreeing: 0, total: Math.max(0, comparable.length - 1) };
    }

    const others = comparable.filter((item) => item.key !== "v9");
    const agreeing = others.filter((item) => item.value === v9).length;
    return {
      text: `${agreeing} / ${others.length} agree with V9 digit ${v9}`,
      agreeing,
      total: others.length,
    };
  }

  function ensureCardPanel(card) {
    const details = card?.querySelector(".v9-details");
    if (!details) return null;

    let panel = details.querySelector(".model-comparison-panel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.className = "model-comparison-panel";
    panel.innerHTML = `
      <div class="model-votes">
        <span>LIVE MODEL COMPARISON</span>
        <strong class="comparison-agreement">WAITING FOR MODELS</strong>
      </div>
      <div class="v9-grid comparison-grid">
        <div><span>V9 Main</span><strong data-model="v9">--</strong></div>
        <div><span>Probability Best</span><strong data-model="proposal">--</strong></div>
        <div><span>Markov</span><strong data-model="markov">--</strong></div>
        <div><span>N-gram</span><strong data-model="sequence">--</strong></div>
        <div><span>HOT 1000</span><strong data-model="hot1000">--</strong></div>
        <div><span>COLD 1000</span><strong data-model="cold1000">--</strong></div>
      </div>
      <div class="gate-blocker comparison-note">
        <span>Agreement Rule</span>
        <strong>Different models may disagree. Agreement is evidence to measure, not a signal by itself.</strong>
      </div>`;

    const blocker = details.querySelector(".gate-blocker");
    if (blocker) details.insertBefore(panel, blocker);
    else details.appendChild(panel);
    return panel;
  }

  function updateCard(symbol, market) {
    const card = cards?.get?.(symbol);
    if (!card) return;
    const panel = ensureCardPanel(card);
    if (!panel) return;

    const candidates = currentCandidates(market);
    candidates.forEach((item) => {
      const node = panel.querySelector(`[data-model="${item.key}"]`);
      if (node) node.textContent = item.value;
    });

    const agreement = agreementSummary(candidates);
    const agreementNode = panel.querySelector(".comparison-agreement");
    if (agreementNode) agreementNode.textContent = agreement.text;
  }

  function ensureLeaderboard() {
    const evidence = document.getElementById("tab-evidence");
    if (!evidence) return null;
    let panel = evidence.querySelector(".strategy-comparison-panel");
    if (panel) return panel;

    panel = document.createElement("article");
    panel.className = "panel strategy-comparison-panel";
    panel.innerHTML = `
      <div class="panel-heading">
        <div><p class="eyebrow">Prospective Strategy Comparison</p><h2>Which approach is actually winning?</h2></div>
        <span class="watch-badge">FORWARD RESULTS ONLY</span>
      </div>
      <p class="evidence-note">These rows use predictions recorded before the next tick. No strategy is promoted from historical frequency alone.</p>
      <div class="evidence-table-wrap">
        <table class="evidence-table">
          <thead><tr><th>Strategy</th><th>Samples</th><th>Accuracy</th><th>95% Lower</th><th>Break-even</th><th>Edge</th><th>Decision</th></tr></thead>
          <tbody class="strategy-comparison-body"><tr><td colspan="7" class="empty-evidence">Loading prospective results...</td></tr></tbody>
        </table>
      </div>`;
    evidence.appendChild(panel);
    return panel;
  }

  function pct(value) {
    return value === null || value === undefined ? dash : `${Number(value).toFixed(2)}%`;
  }

  function edge(value) {
    if (value === null || value === undefined) return dash;
    const n = Number(value);
    return `${n >= 0 ? "+" : ""}${n.toFixed(2)} pp`;
  }

  async function refreshLeaderboard() {
    const panel = ensureLeaderboard();
    const body = panel?.querySelector(".strategy-comparison-body");
    if (!body) return;

    try {
      const response = await fetch("/api/strategy-comparison", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const rows = Array.isArray(payload?.strategies) ? payload.strategies : [];

      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="7" class="empty-evidence">No prospective strategy results yet.</td></tr>';
        return;
      }

      body.innerHTML = rows.map((row) => `
        <tr>
          <td>${String(row.strategy || dash)}</td>
          <td>${Number(row.resolved || 0)}</td>
          <td>${pct(row.accuracy_pct)}</td>
          <td>${pct(row.lower_95_pct)}</td>
          <td>${pct(row.average_break_even_pct)}</td>
          <td>${edge(row.edge_vs_average_break_even_pp)}</td>
          <td>${row.verified_edge ? "EVIDENCE EDGE" : "NO VERIFIED EDGE"}</td>
        </tr>`).join("");
    } catch (error) {
      body.innerHTML = '<tr><td colspan="7" class="empty-evidence">Strategy comparison unavailable.</td></tr>';
      console.warn("Strategy comparison refresh failed", error);
    }
  }

  function refreshCards() {
    if (!latestMarkets || typeof latestMarkets !== "object") return;
    Object.entries(latestMarkets).forEach(([symbol, market]) => updateCard(symbol, market || {}));
  }

  function start() {
    ensureLeaderboard();
    refreshCards();
    refreshLeaderboard();
    window.setInterval(refreshCards, 750);
    window.setInterval(refreshLeaderboard, 10000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
