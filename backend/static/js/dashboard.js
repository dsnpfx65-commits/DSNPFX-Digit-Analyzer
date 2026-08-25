const PREFERRED_ORDER = [
  "1HZ100V", "R_100",
  "1HZ75V", "R_75",
  "1HZ50V", "R_50",
  "1HZ25V", "R_25",
  "1HZ10V", "R_10",
];

const FALLBACK_NAMES = {
  "1HZ100V": "Volatility 100 (1s)",
  "R_100": "Volatility 100",
  "1HZ75V": "Volatility 75 (1s)",
  "R_75": "Volatility 75",
  "1HZ50V": "Volatility 50 (1s)",
  "R_50": "Volatility 50",
  "1HZ25V": "Volatility 25 (1s)",
  "R_25": "Volatility 25",
  "1HZ10V": "Volatility 10 (1s)",
  "R_10": "Volatility 10",
};

const cards = new Map();
let latestMarkets = {};
let currentOrder = [];

const fmtPct = (value) => `${Number(value || 0).toFixed(2)}%`;
const fmtNum = (value) => Number(value || 0).toFixed(2);
const safeText = (value) => (
  value === null || value === undefined || value === "" ? "--" : String(value)
);

function marketName(symbol, market = {}) {
  return market.name || FALLBACK_NAMES[symbol] || symbol;
}

function parseVolatilityRank(symbol, name) {
  const source = `${name || ""} ${symbol || ""}`;
  const match = source.match(/(?:Volatility\s*)?(\d+(?:\.\d+)?)/i);
  return match ? Number(match[1]) : -1;
}

function marketSort(a, b) {
  const aMarket = latestMarkets[a] || {};
  const bMarket = latestMarkets[b] || {};
  const aRank = parseVolatilityRank(a, marketName(a, aMarket));
  const bRank = parseVolatilityRank(b, marketName(b, bMarket));

  if (aRank !== bRank) return bRank - aRank;

  const aOneSecond = /1HZ|1s/i.test(`${a} ${marketName(a, aMarket)}`);
  const bOneSecond = /1HZ|1s/i.test(`${b} ${marketName(b, bMarket)}`);
  if (aOneSecond !== bOneSecond) return aOneSecond ? -1 : 1;

  const aPreferred = PREFERRED_ORDER.indexOf(a);
  const bPreferred = PREFERRED_ORDER.indexOf(b);
  if (aPreferred >= 0 || bPreferred >= 0) {
    if (aPreferred < 0) return 1;
    if (bPreferred < 0) return -1;
    return aPreferred - bPreferred;
  }

  return marketName(a, aMarket).localeCompare(marketName(b, bMarket));
}

function formatAgreement(value) {
  if (!value) return "0 / 0";
  if (typeof value === "object") {
    const agreeing = Number(value.agreeing_models || 0);
    const active = Number(value.active_models || 0);
    return `${agreeing} / ${active}`;
  }
  return safeText(value);
}

function trustedConfidence(market) {
  const samples = Number(market?.rolling_samples || 0);
  return samples > 0 ? fmtPct(market?.calibrated_confidence) : "--";
}

function evidenceNote(market, verified) {
  if (verified) return `Verified confidence ${fmtPct(market?.calibrated_confidence)}`;

  const samples = Number(market?.rolling_samples || 0);
  if (samples < 100) return `Learning trusted evidence ${samples}/100`;

  const reasons = Array.isArray(market?.blocking_reasons)
    ? market.blocking_reasons.filter(Boolean)
    : [];

  return reasons[0] || "NO EDGE / keep scanning";
}

function scannerSignature(market, verified) {
  return JSON.stringify({
    verified,
    prediction: market?.published_prediction ?? null,
    decision: market?.decision || "WAIT",
    quality: market?.market_quality || "LEARNING",
    rollingSamples: Number(market?.rolling_samples || 0),
    rawPremium: Boolean(market?.raw_premium),
  });
}

function createMarketCard(symbol, market = {}) {
  if (cards.has(symbol)) return cards.get(symbol);

  const stack = document.getElementById("marketStack");
  const template = document.getElementById("marketCardTemplate");
  const select = document.getElementById("botMarket");
  const node = template.content.firstElementChild.cloneNode(true);

  node.dataset.symbol = symbol;
  node.querySelector(".market-name").textContent = marketName(symbol, market);
  node.querySelector(".market-mode").textContent = market.mode || "SHADOW";
  node.querySelector(".market-mode").classList.toggle("shadow", (market.mode || "SHADOW") !== "PRODUCTION");
  node.querySelector(".use-signal").addEventListener("click", () => selectSignal(symbol));

  stack.appendChild(node);
  cards.set(symbol, node);

  const option = document.createElement("option");
  option.value = symbol;
  option.textContent = marketName(symbol, market);
  select.appendChild(option);

  return node;
}

function syncMarketCards(markets) {
  const symbols = Object.keys(markets || {}).sort(marketSort);
  currentOrder = symbols;

  const stack = document.getElementById("marketStack");
  const select = document.getElementById("botMarket");

  symbols.forEach((symbol) => createMarketCard(symbol, markets[symbol] || {}));

  symbols.forEach((symbol) => {
    const card = cards.get(symbol);
    if (card) stack.appendChild(card);

    const option = [...select.options].find((item) => item.value === symbol);
    if (option) {
      option.textContent = marketName(symbol, markets[symbol] || {});
      select.appendChild(option);
    }
  });

  for (const [symbol, card] of [...cards.entries()]) {
    if (!symbols.includes(symbol)) {
      card.remove();
      cards.delete(symbol);
      const option = [...select.options].find((item) => item.value === symbol);
      if (option) option.remove();
    }
  }
}

function updateScanner(card, market, verified) {
  const signature = scannerSignature(market, verified);
  if (card._scannerSignature === signature) return;
  card._scannerSignature = signature;

  const digit = card.querySelector(".scanner-digit");
  const label = card.querySelector(".scanner-label");
  const status = card.querySelector(".match-status");
  const note = card.querySelector(".scanner-note");

  clearTimeout(card._revealTimer);
  card.classList.remove("revealed");
  digit.textContent = "--";
  label.textContent = "SCANNING";
  status.textContent = "Analyzing";
  note.textContent = "Checking production evidence";

  const symbol = card.dataset.symbol;
  const delay = 1500 + Math.max(0, currentOrder.indexOf(symbol)) * 60;

  card._revealTimer = setTimeout(() => {
    card.classList.add("revealed");

    if (verified) {
      digit.textContent = safeText(market.published_prediction);
      label.textContent = "PREDICTION";
      status.textContent = "Match Found";
      note.textContent = evidenceNote(market, true);
      return;
    }

    digit.textContent = "--";
    label.textContent = "WAIT";
    status.textContent = Number(market?.rolling_samples || 0) < 100 ? "Learning" : "No Verified Match";
    note.textContent = evidenceNote(market, false);
  }, delay);
}

function updateMarket(symbol, market) {
  const card = createMarketCard(symbol, market);
  const verified = Boolean(
    market && market.is_premium
    && market.published_prediction !== null
    && market.published_prediction !== undefined
  );

  card.classList.toggle("signal", verified);
  card.querySelector(".market-name").textContent = marketName(symbol, market);
  card.querySelector(".market-mode").textContent = market.mode || "SHADOW";
  card.querySelector(".market-mode").classList.toggle("shadow", (market.mode || "SHADOW") !== "PRODUCTION");
  card.querySelector(".live-price").textContent = safeText(market?.displayed_price ?? market?.price);
  card.querySelector(".last-digit").textContent = safeText(market?.last_digit);
  card.querySelector(".market-regime").textContent = safeText(market?.regime || "COLLECTING");
  card.querySelector(".verified-confidence").textContent = trustedConfidence(market);
  card.querySelector(".edge-score").textContent = fmtNum(market?.edge_score);
  card.querySelector(".model-agreement").textContent = formatAgreement(market?.model_agreement);
  card.querySelector(".market-quality").textContent = safeText(market?.market_quality || "LEARNING");
  card.querySelector(".decision-pill").textContent = verified ? "MATCH SIGNAL" : safeText(market?.decision || "WAIT");
  card.querySelector(".use-signal").disabled = !verified;

  updateScanner(card, market, verified);
}

function selectSignal(symbol) {
  const market = latestMarkets[symbol];
  if (!market || !market.is_premium) return;

  document.getElementById("botMarket").value = symbol;
  document.getElementById("botPrediction").value = market.published_prediction;
  document.getElementById("selectedPrediction").textContent = market.published_prediction;
  document.getElementById("selectedMarket").textContent = marketName(symbol, market);
  document.getElementById("selectedDecision").textContent = "MATCH";
  document.getElementById("selectedConfidence").textContent = fmtPct(market.calibrated_confidence);
  document.getElementById("selectedEdge").textContent = fmtNum(market.edge_score);
  document.querySelector('[data-tab="setup"]').click();
}

function updateStats(stats = {}) {
  const pick = (...keys) => {
    for (const key of keys) if (stats[key] !== undefined) return stats[key];
    return 0;
  };

  document.getElementById("productionWins").textContent = pick("production_wins", "wins");
  document.getElementById("productionLosses").textContent = pick("production_losses", "losses");
  document.getElementById("productionAccuracy").textContent = fmtPct(pick("production_accuracy", "accuracy"));
  document.getElementById("recentAccuracy").textContent = fmtPct(pick("recent_accuracy", "last20_accuracy"));
  document.getElementById("resolvedSignals").textContent = pick("resolved_signals", "production_resolved", "resolved");
  document.getElementById("pendingSignals").textContent = pick("pending_signals", "pending");
}

function applyPayload(payload = {}) {
  latestMarkets = payload.markets || latestMarkets || {};
  syncMarketCards(latestMarkets);
  currentOrder.forEach((symbol) => updateMarket(symbol, latestMarkets[symbol] || {}));

  const live = currentOrder.filter((symbol) => {
    const status = latestMarkets[symbol]?.status;
    return status === "live" || status === "LIVE";
  }).length;
  const verified = currentOrder.filter((symbol) => latestMarkets[symbol]?.is_premium).length;

  document.getElementById("onlineMarkets").textContent = `${live} / ${currentOrder.length}`;
  document.getElementById("verifiedSignals").textContent = verified;
  document.getElementById("scannerStatus").textContent = safeText(payload.status || "LIVE").toUpperCase();
  document.getElementById("lastUpdate").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  updateStats(payload.statistics || {});
}

async function initialLoad() {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) return;

    const state = await response.json();
    const [marketsRes, statsRes] = await Promise.all([fetch("/api/markets"), fetch("/api/statistics")]);
    const marketsData = marketsRes.ok ? await marketsRes.json() : {};
    const statsData = statsRes.ok ? await statsRes.json() : {};

    applyPayload({
      ...state,
      markets: Object.fromEntries((marketsData.markets || []).map((market) => [market.symbol, market])),
      statistics: statsData,
    });
  } catch (error) {
    console.warn("Initial dashboard load failed", error);
  }
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/ws`);
  const badge = document.getElementById("connection");

  socket.addEventListener("open", () => {
    badge.classList.add("online");
    badge.innerHTML = "<span></span>LIVE";
  });
  socket.addEventListener("message", (event) => {
    try { applyPayload(JSON.parse(event.data)); }
    catch (error) { console.warn("Invalid websocket payload", error); }
  });
  socket.addEventListener("close", () => {
    badge.classList.remove("online");
    badge.innerHTML = "<span></span>RECONNECTING";
    setTimeout(connectWebSocket, 2500);
  });
  socket.addEventListener("error", () => socket.close());
}

function setupTabs() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab-button").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${button.dataset.tab}`));
    });
  });
}

function setupStrategy() {
  document.getElementById("saveStrategy").addEventListener("click", () => {
    const strategy = {
      market: document.getElementById("botMarket").value,
      stake: document.getElementById("stake").value,
      takeProfit: document.getElementById("takeProfit").value,
      stopLoss: document.getElementById("stopLoss").value,
      martingale: document.getElementById("martingale").value,
      multiplier: document.getElementById("multiplier").value,
      maxLosses: document.getElementById("maxLosses").value,
    };
    localStorage.setItem("dsnpfx-bot-strategy", JSON.stringify(strategy));
    document.getElementById("botMessage").textContent = "Strategy saved locally. Live execution remains disabled until a separate execution module is explicitly enabled.";
  });
}

setupTabs();
setupStrategy();
initialLoad();
connectWebSocket();
