(() => {
  const fmtPctOrDash = (value) => (
    value === null || value === undefined || Number.isNaN(Number(value))
      ? "--"
      : `${Number(value).toFixed(2)}%`
  );

  const fmtMoneyOrDash = (value, currency = "") => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
    const amount = Number(value).toFixed(2);
    return currency ? `${currency} ${amount}` : amount;
  };

  const fmtEdgeOrDash = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
    const number = Number(value);
    return `${number >= 0 ? "+" : ""}${number.toFixed(2)} pp`;
  };

  function probabilityAnalysis(market) {
    const metadata = market?.model_metadata;
    if (!metadata || typeof metadata !== "object") return {};
    const analysis = metadata.probability_analysis;
    return analysis && typeof analysis === "object" ? analysis : {};
  }

  function edgeStatus(analysis) {
    const quoteStatus = String(analysis?.proposal_quote_status || "WAITING").toUpperCase();
    const action = String(analysis?.payout_action || analysis?.research_action || "NO_TRADE").toUpperCase();
    const edge = Number(analysis?.estimated_edge_vs_break_even_pp);

    if (quoteStatus !== "LIVE") {
      return { label: "WAITING QUOTE", className: "waiting" };
    }
    if (action === "WATCH" && Number.isFinite(edge) && edge > 0) {
      return { label: "WATCH", className: "watch" };
    }
    return { label: "NO TRADE", className: "no-trade" };
  }

  function updateProposalEdge(card, market) {
    if (!card) return;
    const analysis = probabilityAnalysis(market);
    const status = edgeStatus(analysis);

    const nodes = {
      bestDigit: card.querySelector(".proposal-best-digit"),
      estimate: card.querySelector(".proposal-model-estimate"),
      breakEven: card.querySelector(".proposal-break-even"),
      edge: card.querySelector(".proposal-edge"),
      ask: card.querySelector(".proposal-ask"),
      payout: card.querySelector(".proposal-payout"),
      status: card.querySelector(".proposal-status"),
      reliability: card.querySelector(".proposal-reliability"),
    };

    if (nodes.bestDigit) nodes.bestDigit.textContent = analysis?.best_match_digit ?? "--";
    if (nodes.estimate) nodes.estimate.textContent = fmtPctOrDash(analysis?.best_match_estimate_pct);
    if (nodes.breakEven) nodes.breakEven.textContent = fmtPctOrDash(analysis?.break_even_probability_pct);
    if (nodes.edge) nodes.edge.textContent = fmtEdgeOrDash(analysis?.estimated_edge_vs_break_even_pp);
    if (nodes.ask) nodes.ask.textContent = fmtMoneyOrDash(analysis?.proposal_ask_price, analysis?.proposal_currency);
    if (nodes.payout) nodes.payout.textContent = fmtMoneyOrDash(analysis?.proposal_payout, analysis?.proposal_currency);
    if (nodes.reliability) nodes.reliability.textContent = fmtPctOrDash(analysis?.research_reliability_pct);
    if (nodes.status) {
      nodes.status.textContent = status.label;
      nodes.status.className = `proposal-status ${status.className}`;
    }
  }

  if (typeof updateMarket === "function") {
    const originalUpdateMarket = updateMarket;
    updateMarket = function proposalAwareUpdateMarket(symbol, market) {
      originalUpdateMarket(symbol, market);
      const card = typeof cards !== "undefined" ? cards.get(symbol) : null;
      updateProposalEdge(card, market);
    };
  }

  window.DSNPFXProposalEdgeUI = { updateProposalEdge };
})();
