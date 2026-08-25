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

  function hot1000Analysis(market) {
    const metadata = market?.model_metadata;
    if (!metadata || typeof metadata !== "object") return {};
    const analysis = metadata.hot_1000_continuation;
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

  function ensureHot1000Panel(card) {
    if (!card) return null;
    const details = card.querySelector(".v9-details");
    if (!details) return null;

    let panel = details.querySelector(".hot1000-research-panel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.className = "hot1000-research-panel";
    panel.innerHTML = `
      <div class="model-votes">
        <span>HOT 1000 CONTINUATION · RESEARCH ONLY</span>
        <strong class="hot1000-status">COLLECTING 0/1000</strong>
      </div>
      <div class="v9-grid hot1000-grid">
        <div><span>Hot Digit</span><strong class="hot1000-digit">--</strong></div>
        <div><span>1000-Tick Frequency</span><strong class="hot1000-frequency">--</strong></div>
        <div><span>Deviation vs 10%</span><strong class="hot1000-deviation">--</strong></div>
        <div><span>Z-Score</span><strong class="hot1000-z">--</strong></div>
        <div><span>Window Agreement</span><strong class="hot1000-agreement">--</strong></div>
        <div><span>Duration</span><strong>1 tick</strong></div>
      </div>
      <div class="gate-blocker">
        <span>Hot 1000 Rule</span>
        <strong class="hot1000-note">Collect 1000 displayed last digits before testing the next-tick continuation hypothesis.</strong>
      </div>
    `;

    const blocker = details.querySelector(".gate-blocker");
    if (blocker) {
      details.insertBefore(panel, blocker);
    } else {
      details.appendChild(panel);
    }
    return panel;
  }

  function updateHot1000(card, market) {
    if (!card) return;
    const panel = ensureHot1000Panel(card);
    if (!panel) return;

    const analysis = hot1000Analysis(market);
    const status = String(analysis?.status || "COLLECTING").toUpperCase();
    const samples = Number(analysis?.samples || 0);
    const required = Number(analysis?.samples_required || 1000);

    const statusNode = panel.querySelector(".hot1000-status");
    if (statusNode) {
      if (status === "COLLECTING") {
        statusNode.textContent = `COLLECTING ${samples}/${required}`;
      } else if (status === "TIED_HOT_DIGITS") {
        statusNode.textContent = "TIED · WAIT";
      } else {
        statusNode.textContent = "READY · FORWARD TEST";
      }
    }

    const digit = panel.querySelector(".hot1000-digit");
    const frequency = panel.querySelector(".hot1000-frequency");
    const deviation = panel.querySelector(".hot1000-deviation");
    const zscore = panel.querySelector(".hot1000-z");
    const agreement = panel.querySelector(".hot1000-agreement");
    const note = panel.querySelector(".hot1000-note");

    if (digit) digit.textContent = analysis?.candidate ?? "--";
    if (frequency) frequency.textContent = fmtPctOrDash(analysis?.frequency_pct);
    if (deviation) deviation.textContent = fmtEdgeOrDash(analysis?.deviation_vs_10pct_pp);
    if (zscore) {
      zscore.textContent = analysis?.z_score === null || analysis?.z_score === undefined
        ? "--"
        : Number(analysis.z_score).toFixed(2);
    }
    if (agreement) agreement.textContent = fmtPctOrDash(analysis?.continuation_consistency_pct);
    if (note) {
      note.textContent = status === "READY"
        ? "Hot digit is a research candidate only. Forward next-tick results must beat the live Match break-even rate before promotion."
        : status === "TIED_HOT_DIGITS"
          ? "The 1000-tick window has multiple equally hot digits, so this strategy produces no candidate."
          : `Collecting the exact 1000-tick sample required by the video strategy: ${samples}/${required}.`;
    }
  }

  if (typeof updateMarket === "function") {
    const originalUpdateMarket = updateMarket;
    updateMarket = function proposalAwareUpdateMarket(symbol, market) {
      originalUpdateMarket(symbol, market);
      const card = typeof cards !== "undefined" ? cards.get(symbol) : null;
      updateProposalEdge(card, market);
      updateHot1000(card, market);
    };
  }

  window.DSNPFXProposalEdgeUI = { updateProposalEdge, updateHot1000 };
})();
