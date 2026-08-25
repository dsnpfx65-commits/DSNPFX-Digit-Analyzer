const EVIDENCE_BASELINE = 10.0;

function watchFmtPct(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function watchMarketName(market) {
  return market?.name || market?.symbol || "Unknown";
}

function watchAgreement(market) {
  const value = market?.model_agreement;
  if (!value || typeof value !== "object") return "0 / 0";
  return `${Number(value.agreeing_models || 0)} / ${Number(value.active_models || 0)}`;
}

function bestForwardModel(market) {
  const stats = market?.model_statistics;
  if (!stats || typeof stats !== "object") {
    return { name: "--", accuracy: null, samples: 0 };
  }

  const labels = {
    frequency: "Frequency",
    markov: "Markov",
    sequence: "N-gram",
  };

  const candidates = Object.entries(stats)
    .filter(([model]) => labels[model])
    .map(([model, value]) => ({
      name: labels[model],
      accuracy: Number(value?.recent_accuracy ?? value?.accuracy ?? 0),
      samples: Number(value?.recent_samples ?? value?.samples ?? 0),
    }))
    .filter((item) => item.samples > 0)
    .sort((a, b) => {
      if (a.accuracy !== b.accuracy) return b.accuracy - a.accuracy;
      return b.samples - a.samples;
    });

  return candidates[0] || { name: "--", accuracy: null, samples: 0 };
}

function evidenceStatus(market) {
  const samples = Number(market?.rolling_samples || 0);
  const accuracy = Number(market?.rolling_accuracy || 0);
  const lower = Number(market?.rolling_lower_bound || 0);

  if (market?.statistically_above_baseline === true && lower > EVIDENCE_BASELINE) {
    return { label: "EVIDENCE EDGE", className: "verified", rank: 4 };
  }

  if (samples >= 30 && accuracy > EVIDENCE_BASELINE) {
    return { label: "PROMISING", className: "promising", rank: 3 };
  }

  if (samples < 100) {
    return { label: "LEARNING", className: "learning", rank: 2 };
  }

  return { label: "NO VERIFIED EDGE", className: "no-edge", rank: 1 };
}

function renderEvidenceRows(markets) {
  const body = document.getElementById("evidenceWatchBody");
  const above = document.getElementById("marketsAboveBaseline");
  if (!body || !above) return;

  const rows = (markets || [])
    .filter((market) => market && market.symbol)
    .map((market) => ({
      market,
      status: evidenceStatus(market),
      bestModel: bestForwardModel(market),
    }))
    .sort((a, b) => {
      if (a.status.rank !== b.status.rank) return b.status.rank - a.status.rank;

      const lowerDiff = Number(b.market.rolling_lower_bound || 0)
        - Number(a.market.rolling_lower_bound || 0);
      if (lowerDiff !== 0) return lowerDiff;

      const sampleDiff = Number(b.market.rolling_samples || 0)
        - Number(a.market.rolling_samples || 0);
      if (sampleDiff !== 0) return sampleDiff;

      return watchMarketName(a.market).localeCompare(watchMarketName(b.market));
    });

  const evidenceEdges = rows.filter((row) => row.status.rank === 4).length;
  above.textContent = evidenceEdges;

  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty-evidence">Waiting for prospective shadow outcomes...</td></tr>';
    return;
  }

  body.replaceChildren();

  for (const row of rows) {
    const market = row.market;
    const tr = document.createElement("tr");

    const marketCell = document.createElement("td");
    marketCell.className = "market-cell";
    const marketStrong = document.createElement("strong");
    marketStrong.textContent = watchMarketName(market);
    const marketSymbol = document.createElement("span");
    marketSymbol.textContent = market.symbol;
    marketCell.append(marketStrong, marketSymbol);

    const samplesCell = document.createElement("td");
    samplesCell.textContent = `${Number(market.rolling_samples || 0)} / 100`;

    const accuracyCell = document.createElement("td");
    accuracyCell.textContent = Number(market.rolling_samples || 0) > 0
      ? watchFmtPct(market.rolling_accuracy)
      : "--";

    const lowerCell = document.createElement("td");
    const lower = Number(market.rolling_lower_bound || 0);
    lowerCell.textContent = Number(market.rolling_samples || 0) > 0
      ? watchFmtPct(lower)
      : "--";
    lowerCell.className = `lower-bound ${lower > EVIDENCE_BASELINE ? "good" : "weak"}`;

    const agreementCell = document.createElement("td");
    agreementCell.textContent = watchAgreement(market);

    const modelCell = document.createElement("td");
    modelCell.className = "best-model";
    const modelName = document.createElement("span");
    modelName.textContent = row.bestModel.name;
    const modelMeta = document.createElement("small");
    modelMeta.textContent = row.bestModel.samples > 0
      ? `${watchFmtPct(row.bestModel.accuracy)} · n=${row.bestModel.samples}`
      : "No resolved model evidence";
    modelCell.append(modelName, modelMeta);

    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `edge-status ${row.status.className}`;
    badge.textContent = row.status.label;
    statusCell.appendChild(badge);

    tr.append(
      marketCell,
      samplesCell,
      accuracyCell,
      lowerCell,
      agreementCell,
      modelCell,
      statusCell,
    );

    body.appendChild(tr);
  }
}

function renderShadowSummary(stats) {
  const shadow = stats?.shadow || {};
  const shadowRolling = stats?.shadow_rolling || {};
  const research = stats?.research || {};

  const values = {
    shadowResolved: Number(shadow.resolved || 0),
    shadowAccuracy: watchFmtPct(shadow.accuracy),
    shadowRecentAccuracy: watchFmtPct(shadowRolling.accuracy),
    researchResolved: Number(research.resolved || 0),
    shadowPending: Number(stats?.pending || 0),
  };

  for (const [id, value] of Object.entries(values)) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }
}

async function refreshEvidenceWatch() {
  try {
    const [marketsResponse, statsResponse] = await Promise.all([
      fetch("/api/markets", { cache: "no-store" }),
      fetch("/api/statistics", { cache: "no-store" }),
    ]);

    const marketsPayload = marketsResponse.ok ? await marketsResponse.json() : {};
    const statsPayload = statsResponse.ok ? await statsResponse.json() : {};

    renderEvidenceRows(marketsPayload.markets || []);
    renderShadowSummary(statsPayload || {});
  } catch (error) {
    console.warn("V9 evidence watch refresh failed", error);
  }
}

refreshEvidenceWatch();
setInterval(refreshEvidenceWatch, 3000);
