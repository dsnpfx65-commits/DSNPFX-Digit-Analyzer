(() => {
  "use strict";

  const POLL_MS = 5000;
  const CHECKPOINTS = [100, 250, 500];
  const MODEL_LABELS = {
    frequency: "Frequency",
    markov: "Markov",
    sequence: "Sequence",
    probability_best: "Probability Best",
    hot_1000: "HOT 1000",
    cold_1000: "COLD 1000",
  };

  function relabelStaticShell() {
    const introEyebrow = document.querySelector(".intro-card .eyebrow");
    if (introEyebrow) introEyebrow.textContent = "Live Market Scanner · V10 Adaptive Forward Ensemble";

    const introCopy = document.querySelector(".intro-card .intro-copy");
    if (introCopy) {
      introCopy.textContent = "Every supported Volatility market is scanned continuously from the Deriv Options / Digits tick feed. V10 allows only the Adaptive Forward Ensemble to select the authoritative Match digit. The scanner reveals a digit only after the production evidence gate approves it. All other model digits remain research evidence only.";
    }

    document.querySelectorAll(".heading-meta .research-badge").forEach((badge) => {
      if (badge.textContent.includes("Candidate")) badge.textContent = "One Authority · Adaptive Forward";
    });

    const evidenceEyebrow = document.querySelector(".evidence-watch-heading .eyebrow");
    if (evidenceEyebrow) evidenceEyebrow.textContent = "V10 Forward Evidence Watch";
  }

  function authoritativeState(market = {}) {
    const published = market?.published_prediction;
    const verified = Boolean(market?.is_premium && published !== null && published !== undefined);
    return { verified, published };
  }

  function enforceAuthorityScanner(card, market = {}) {
    if (!card) return;
    const { verified, published } = authoritativeState(market);
    const digit = card.querySelector(".scanner-digit");
    const label = card.querySelector(".scanner-label");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");

    if (verified) {
      if (digit && String(digit.textContent).trim() !== String(published)) digit.textContent = String(published);
      if (label && label.textContent !== "PREDICTION") label.textContent = "PREDICTION";
      if (status && status.textContent !== "Match Found") status.textContent = "Match Found";
      return;
    }

    if (digit && digit.textContent !== "--" && label?.textContent !== "TEST PREDICTION") digit.textContent = "--";
    if (label && (label.textContent === "CANDIDATE" || label.textContent === "PREDICTION")) label.textContent = "WAIT";
    if (status && status.textContent === "Research Candidate") status.textContent = "No Verified Prediction";
    if (note && /NOT VERIFIED|research candidate/i.test(note.textContent || "")) {
      note.textContent = "V10 authority has not verified a digit · rescanning";
    }
  }

  function relabelCard(card, market = {}) {
    if (!card) return;
    const candidate = market?.candidate_prediction;
    const { verified: isVerified } = authoritativeState(market);
    const hasAuthority = candidate !== null && candidate !== undefined;

    const regimeSmall = card.querySelector(".market-tick-row > div:nth-child(3) small");
    if (regimeSmall) regimeSmall.textContent = "V10 analysis";

    const candidateLabel = card.querySelector(".candidate-strip > div:first-child span");
    if (candidateLabel) candidateLabel.textContent = "V10 Adaptive Authority";

    const candidateDigit = card.querySelector(".candidate-digit");
    if (candidateDigit) candidateDigit.textContent = hasAuthority ? String(candidate) : "--";

    const warning = card.querySelector(".candidate-warning");
    if (warning) {
      warning.textContent = isVerified
        ? "Verified V10 Match signal — adaptive authority and production gate approved."
        : hasAuthority
          ? "V10 selected one forward-verified digit, but the production gate has not approved a trade signal."
          : "No forward-verified adaptive prediction yet — research models cannot publish a digit.";
    }

    const summary = card.querySelector(".v9-details > summary");
    if (summary) summary.textContent = "Research Models · Evidence Only";

    const proposalLabel = card.querySelector(".proposal-best-digit")?.parentElement?.querySelector("span");
    if (proposalLabel) proposalLabel.textContent = "Research Best Match";

    const proposalHeadingSmall = card.querySelector(".proposal-edge-heading small");
    if (proposalHeadingSmall) proposalHeadingSmall.textContent = "Research only · never becomes the published digit directly";

    const modelVotesLabel = card.querySelector(".model-votes > span");
    if (modelVotesLabel && modelVotesLabel.textContent === "Voting Models") modelVotesLabel.textContent = "Research Model Votes";

    const confidenceLabel = card.querySelector(".verified-confidence")?.parentElement?.querySelector("span");
    if (confidenceLabel) confidenceLabel.textContent = "Production Evidence Confidence";

    enforceAuthorityScanner(card, market);
  }

  function marketForCard(card) {
    const symbol = card?.dataset?.symbol;
    return (typeof latestMarkets === "object" && latestMarkets && symbol) ? (latestMarkets[symbol] || {}) : {};
  }

  function relabelAllCards() {
    document.querySelectorAll(".market-card").forEach((card) => relabelCard(card, marketForCard(card)));
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    }[character]));
  }

  function pct(value) {
    const number = Number(value);
    return Number.isFinite(number) ? `${number.toFixed(2)}%` : "--";
  }

  function pp(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "--";
    return `${number >= 0 ? "+" : ""}${number.toFixed(2)} pp`;
  }

  function modelLabel(key) {
    return MODEL_LABELS[key] || String(key || "Unknown");
  }

  function checkpoint(resolved) {
    const n = Number(resolved || 0);
    const next = CHECKPOINTS.find((target) => n < target);
    return next ? `${Math.min(n, next)} / ${next}` : `${n} / 500+`;
  }

  function leaderForMarket(market) {
    const rows = Array.isArray(market?.models) ? market.models : [];
    const ranked = rows
      .filter((row) => Number(row?.resolved || 0) > 0)
      .slice()
      .sort((a, b) => {
        const aEnough = Number(a.resolved || 0) >= 100 ? 1 : 0;
        const bEnough = Number(b.resolved || 0) >= 100 ? 1 : 0;
        if (aEnough !== bEnough) return bEnough - aEnough;
        const lower = Number(b.lower_95_pct || 0) - Number(a.lower_95_pct || 0);
        if (lower !== 0) return lower;
        return Number(b.accuracy_pct || 0) - Number(a.accuracy_pct || 0);
      });
    return ranked[0] || null;
  }

  function rowStatus(row) {
    const n = Number(row?.resolved || 0);
    if (row?.tradable_eligible) return "ECONOMIC EDGE";
    if (row?.statistical_eligible) return "ABOVE 10%";
    if (n < 100) return "COLLECTING";
    return "NO VERIFIED EDGE";
  }

  function injectLeaderboardStyles() {
    if (document.getElementById("dsnpfx-model-leaderboard-style")) return;
    const style = document.createElement("style");
    style.id = "dsnpfx-model-leaderboard-style";
    style.textContent = `
      .model-leaderboard-panel{margin-top:18px}
      .model-leaderboard-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0}
      .model-leaderboard-summary>div{padding:12px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.025)}
      .model-leaderboard-summary span{display:block;font-size:11px;opacity:.62;text-transform:uppercase;letter-spacing:.07em}
      .model-leaderboard-summary strong{display:block;margin-top:5px;font-size:17px}
      .model-market-block{margin-top:14px;border:1px solid rgba(255,255,255,.08);border-radius:14px;overflow:hidden}
      .model-market-head{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px 14px;background:rgba(255,255,255,.025)}
      .model-market-head small{opacity:.62}
      .model-leaderboard-table-wrap{overflow-x:auto}
      .model-leaderboard-table{width:100%;border-collapse:collapse;min-width:820px}
      .model-leaderboard-table th,.model-leaderboard-table td{padding:10px 12px;text-align:left;border-top:1px solid rgba(255,255,255,.07);font-size:12px}
      .model-leaderboard-table th{opacity:.6;text-transform:uppercase;letter-spacing:.05em;font-size:10px}
      .model-leader{font-weight:700}
      .model-status-edge{font-weight:700}
      .model-leaderboard-note{margin-top:12px;font-size:12px;opacity:.68;line-height:1.5}
    `;
    document.head.appendChild(style);
  }

  function ensureLeaderboardPanel() {
    const evidence = document.getElementById("tab-evidence");
    if (!evidence) return null;
    let panel = document.getElementById("modelAccuracyLeaderboard");
    if (panel) return panel;

    panel = document.createElement("article");
    panel.id = "modelAccuracyLeaderboard";
    panel.className = "panel model-leaderboard-panel";
    panel.innerHTML = `
      <div class="panel-heading">
        <div><p class="eyebrow">Exact Next-Tick Forward Audit</p><h2>Model Accuracy Leaderboard</h2></div>
        <span class="watch-badge">100 · 250 · 500 checkpoints</span>
      </div>
      <div class="model-leaderboard-summary">
        <div><span>Markets Audited</span><strong data-leaderboard="markets">0</strong></div>
        <div><span>Models With 100+</span><strong data-leaderboard="qualified">0</strong></div>
        <div><span>Economic Edge Models</span><strong data-leaderboard="edge">0</strong></div>
        <div><span>Last Refresh</span><strong data-leaderboard="updated">--</strong></div>
      </div>
      <div data-leaderboard="body"><p class="model-leaderboard-note">Waiting for prospective next-tick model results...</p></div>
      <p class="model-leaderboard-note">Rankings use predictions committed before settlement. A high raw accuracy is not enough: the 95% lower confidence bound and live DIGITMATCH break-even are shown so short streaks are not mistaken for verified edge.</p>
    `;
    evidence.appendChild(panel);
    return panel;
  }

  function renderLeaderboard(payload) {
    const panel = ensureLeaderboardPanel();
    if (!panel) return;
    const markets = Array.isArray(payload?.markets) ? payload.markets : [];
    const allRows = markets.flatMap((market) => Array.isArray(market.models) ? market.models : []);
    const qualified = allRows.filter((row) => Number(row.resolved || 0) >= 100).length;
    const edge = allRows.filter((row) => row.tradable_eligible).length;

    panel.querySelector('[data-leaderboard="markets"]').textContent = String(markets.length);
    panel.querySelector('[data-leaderboard="qualified"]').textContent = String(qualified);
    panel.querySelector('[data-leaderboard="edge"]').textContent = String(edge);
    panel.querySelector('[data-leaderboard="updated"]').textContent = new Date().toLocaleTimeString();

    const body = panel.querySelector('[data-leaderboard="body"]');
    if (!markets.length) {
      body.innerHTML = '<p class="model-leaderboard-note">No model audit data is available yet.</p>';
      return;
    }

    body.innerHTML = markets.map((market) => {
      const leader = leaderForMarket(market);
      const rows = (market.models || []).slice().sort((a, b) => {
        const aLeader = leader && a.model === leader.model ? 1 : 0;
        const bLeader = leader && b.model === leader.model ? 1 : 0;
        if (aLeader !== bLeader) return bLeader - aLeader;
        return Number(b.lower_95_pct || 0) - Number(a.lower_95_pct || 0);
      });
      const leaderText = leader
        ? `${modelLabel(leader.model)} · ${pct(leader.accuracy_pct)} · n=${Number(leader.resolved || 0)}`
        : "Collecting";

      return `
        <section class="model-market-block">
          <div class="model-market-head">
            <div><strong>${escapeHtml(market.symbol)}</strong><br><small>Best current forward evidence</small></div>
            <strong>${escapeHtml(leaderText)}</strong>
          </div>
          <div class="model-leaderboard-table-wrap">
            <table class="model-leaderboard-table">
              <thead><tr><th>Model</th><th>Accuracy</th><th>N</th><th>95% Lower</th><th>Recent</th><th>Avg B/E</th><th>Edge vs B/E</th><th>Checkpoint</th><th>Status</th></tr></thead>
              <tbody>
                ${rows.map((row) => {
                  const isLeader = leader && row.model === leader.model;
                  return `<tr>
                    <td class="${isLeader ? "model-leader" : ""}">${escapeHtml(modelLabel(row.model))}${isLeader ? " ★" : ""}</td>
                    <td>${pct(row.accuracy_pct)}</td>
                    <td>${Number(row.resolved || 0)}</td>
                    <td>${pct(row.lower_95_pct)}</td>
                    <td>${pct(row.recent_accuracy_pct)}</td>
                    <td>${pct(row.average_break_even_pct)}</td>
                    <td>${pp(row.edge_vs_break_even_pp)}</td>
                    <td>${escapeHtml(checkpoint(row.resolved))}</td>
                    <td class="${row.tradable_eligible ? "model-status-edge" : ""}">${escapeHtml(rowStatus(row))}</td>
                  </tr>`;
                }).join("")}
              </tbody>
            </table>
          </div>
        </section>`;
    }).join("");
  }

  async function refreshLeaderboard() {
    try {
      const response = await fetch("/api/adaptive-forward-results", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderLeaderboard(await response.json());
    } catch (error) {
      const panel = ensureLeaderboardPanel();
      const body = panel?.querySelector('[data-leaderboard="body"]');
      if (body) body.innerHTML = `<p class="model-leaderboard-note">Leaderboard temporarily unavailable: ${escapeHtml(error?.message || error)}</p>`;
    }
  }

  relabelStaticShell();

  if (typeof window.updateMarket === "function") {
    const baseUpdateMarket = window.updateMarket;
    window.updateMarket = function dsnpfxV10UpdateMarket(symbol, market) {
      const result = baseUpdateMarket(symbol, market);
      const card = (typeof cards !== "undefined" && cards?.get) ? cards.get(symbol) : document.querySelector(`.market-card[data-symbol="${symbol}"]`);
      relabelCard(card, market || {});
      return result;
    };
  }

  if (typeof window.applyPayload === "function") {
    const baseApplyPayload = window.applyPayload;
    window.applyPayload = function dsnpfxV10ApplyPayload(payload) {
      const result = baseApplyPayload(payload);
      relabelAllCards();
      return result;
    };
  }

  document.addEventListener("DOMContentLoaded", () => {
    relabelStaticShell();
    relabelAllCards();
    injectLeaderboardStyles();
    ensureLeaderboardPanel();
    refreshLeaderboard();

    const stack = document.getElementById("marketStack");
    if (stack && typeof MutationObserver === "function") {
      let scheduled = false;
      const observer = new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(() => {
          scheduled = false;
          relabelAllCards();
        });
      });
      observer.observe(stack, { subtree: true, childList: true, characterData: true });
    }
  });

  setTimeout(() => {
    injectLeaderboardStyles();
    ensureLeaderboardPanel();
    relabelAllCards();
    refreshLeaderboard();
  }, 0);
  setInterval(refreshLeaderboard, POLL_MS);
})();
