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

  function modelMetadata(market) {
    const metadata = market?.model_metadata;
    return metadata && typeof metadata === "object" ? metadata : {};
  }

  function probabilityAnalysis(market) {
    const analysis = modelMetadata(market).probability_analysis;
    return analysis && typeof analysis === "object" ? analysis : {};
  }

  function hot1000Analysis(market) {
    const analysis = modelMetadata(market).hot_1000_continuation;
    return analysis && typeof analysis === "object" ? analysis : {};
  }

  function coldReversionAnalysis(market) {
    const analysis = modelMetadata(market).cold_reversion;
    return analysis && typeof analysis === "object" ? analysis : {};
  }

  function cold20DiffersAnalysis(market) {
    const analysis = modelMetadata(market).cold_20_differs;
    return analysis && typeof analysis === "object" ? analysis : {};
  }

  function coldWindow(analysis, window) {
    const windows = analysis?.windows;
    if (!windows || typeof windows !== "object") return {};
    return windows[window] || windows[String(window)] || {};
  }

  function edgeStatus(analysis) {
    const quoteStatus = String(analysis?.proposal_quote_status || "WAITING").toUpperCase();
    const action = String(analysis?.payout_action || analysis?.research_action || "NO_TRADE").toUpperCase();
    const edge = Number(analysis?.estimated_edge_vs_break_even_pp);

    if (quoteStatus !== "LIVE") return { label: "WAITING QUOTE", className: "waiting" };
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
      </div>`;

    const blocker = details.querySelector(".gate-blocker");
    if (blocker) details.insertBefore(panel, blocker);
    else details.appendChild(panel);
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
      if (status === "COLLECTING") statusNode.textContent = `COLLECTING ${samples}/${required}`;
      else if (status === "TIED_HOT_DIGITS") statusNode.textContent = "TIED · WAIT";
      else statusNode.textContent = "READY · FORWARD TEST";
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
    if (zscore) zscore.textContent = analysis?.z_score == null ? "--" : Number(analysis.z_score).toFixed(2);
    if (agreement) agreement.textContent = fmtPctOrDash(analysis?.continuation_consistency_pct);
    if (note) {
      note.textContent = status === "READY"
        ? "Hot digit is a research candidate only. Forward next-tick results must beat the live Match break-even rate before promotion."
        : status === "TIED_HOT_DIGITS"
          ? "The 1000-tick window has multiple equally hot digits, so this strategy produces no candidate."
          : `Collecting the exact 1000-tick sample required by the continuation hypothesis: ${samples}/${required}.`;
    }
  }

  function ensureColdPanel(card) {
    if (!card) return null;
    const details = card.querySelector(".v9-details");
    if (!details) return null;
    let panel = details.querySelector(".cold-reversion-research-panel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.className = "cold-reversion-research-panel";
    panel.innerHTML = `
      <div class="model-votes">
        <span>COLD REVERSION · RESEARCH ONLY</span>
        <strong class="cold-status">COLLECTING</strong>
      </div>
      <div class="v9-grid cold-reversion-grid">
        <div><span>Cold 200</span><strong class="cold-200">--</strong></div>
        <div><span>Cold 500</span><strong class="cold-500">--</strong></div>
        <div><span>Cold 1000</span><strong class="cold-1000">--</strong></div>
        <div><span>Primary Window</span><strong class="cold-primary-window">--</strong></div>
        <div><span>Primary Digit</span><strong class="cold-primary-digit">--</strong></div>
        <div><span>Duration</span><strong>1 tick</strong></div>
      </div>
      <div class="gate-blocker">
        <span>Cold Reversion Rule</span>
        <strong class="cold-note">A rare digit is not automatically due. Each window is forward-tested independently.</strong>
      </div>`;

    details.appendChild(panel);
    return panel;
  }

  function coldCandidateText(report) {
    const status = String(report?.status || "COLLECTING").toUpperCase();
    if (status === "COLLECTING") {
      return `COLLECTING ${Number(report?.samples || 0)}/${Number(report?.samples_required || 0)}`;
    }
    if (status === "TIED_COLD_DIGITS") return "TIED · WAIT";
    if (report?.candidate == null) return "--";
    return `MATCH ${report.candidate} · ${fmtPctOrDash(report.frequency_pct)} · ${fmtEdgeOrDash(report.deviation_vs_10pct_pp)}`;
  }

  function updateColdReversion(card, market) {
    if (!card) return;
    const panel = ensureColdPanel(card);
    if (!panel) return;
    const analysis = coldReversionAnalysis(market);
    const report200 = coldWindow(analysis, 200);
    const report500 = coldWindow(analysis, 500);
    const report1000 = coldWindow(analysis, 1000);

    const status = panel.querySelector(".cold-status");
    const cold200 = panel.querySelector(".cold-200");
    const cold500 = panel.querySelector(".cold-500");
    const cold1000 = panel.querySelector(".cold-1000");
    const primaryWindow = panel.querySelector(".cold-primary-window");
    const primaryDigit = panel.querySelector(".cold-primary-digit");
    const note = panel.querySelector(".cold-note");

    if (status) status.textContent = String(analysis?.status || "COLLECTING").toUpperCase();
    if (cold200) cold200.textContent = coldCandidateText(report200);
    if (cold500) cold500.textContent = coldCandidateText(report500);
    if (cold1000) cold1000.textContent = coldCandidateText(report1000);
    if (primaryWindow) primaryWindow.textContent = analysis?.primary_window ?? "--";
    if (primaryDigit) primaryDigit.textContent = analysis?.primary_candidate ?? "--";

    if (note) {
      const hot = hot1000Analysis(market);
      const coldDigit = analysis?.primary_candidate;
      const hotDigit = hot?.candidate;
      if (coldDigit != null && hotDigit != null) {
        note.textContent = Number(coldDigit) === Number(hotDigit)
          ? `HOT and COLD currently point to digit ${coldDigit}, but for opposite reasons. Forward evidence decides whether either hypothesis has edge.`
          : `Current comparison: HOT ${hotDigit} vs COLD ${coldDigit}. Both remain research-only until prospective results beat break-even.`;
      } else {
        note.textContent = "A rare digit is not automatically due. Cold 200/500/1000 are forward-tested independently against HOT 1000 and the live Match break-even rate.";
      }
    }
  }

  function ensureCold20DiffersPanel(card) {
    if (!card) return null;
    const details = card.querySelector(".v9-details");
    if (!details) return null;
    let panel = details.querySelector(".cold20-differs-panel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.className = "cold20-differs-panel";
    panel.innerHTML = `
      <div class="model-votes">
        <span>COLD 20 DIFFERS · RESEARCH ONLY</span>
        <strong class="cold20-status">COLLECTING 0/20</strong>
      </div>
      <div class="v9-grid cold20-grid">
        <div><span>Cold Digit</span><strong class="cold20-digit">--</strong></div>
        <div><span>20-Tick Frequency</span><strong class="cold20-frequency">--</strong></div>
        <div><span>Historical Differ Rate</span><strong class="cold20-historical-differ">--</strong></div>
        <div><span>Natural Differ Baseline</span><strong>90.00%</strong></div>
        <div><span>Live Break-even</span><strong class="cold20-break-even">--</strong></div>
        <div><span>90% Baseline vs Break-even</span><strong class="cold20-baseline-edge">--</strong></div>
        <div><span>Ask</span><strong class="cold20-ask">--</strong></div>
        <div><span>Payout</span><strong class="cold20-payout">--</strong></div>
        <div><span>Duration</span><strong>1 tick</strong></div>
      </div>
      <div class="gate-blocker">
        <span>Cold 20 Rule</span>
        <strong class="cold20-note">Find a unique coldest digit in the latest 20 ticks, then forward-test DIGITDIFF on the next tick. Historical frequency is not next-tick probability.</strong>
      </div>`;

    details.appendChild(panel);
    return panel;
  }

  function updateCold20Differs(card, market) {
    if (!card) return;
    const panel = ensureCold20DiffersPanel(card);
    if (!panel) return;
    const analysis = cold20DiffersAnalysis(market);
    const status = String(analysis?.status || "COLLECTING").toUpperCase();
    const samples = Number(analysis?.samples || 0);
    const required = Number(analysis?.samples_required || 20);

    const statusNode = panel.querySelector(".cold20-status");
    if (statusNode) {
      if (status === "COLLECTING") statusNode.textContent = `COLLECTING ${samples}/${required}`;
      else if (status === "TIED_COLD_DIGITS") statusNode.textContent = "TIED · WAIT";
      else statusNode.textContent = "READY · FORWARD TEST";
    }

    const digit = panel.querySelector(".cold20-digit");
    const freq = panel.querySelector(".cold20-frequency");
    const hist = panel.querySelector(".cold20-historical-differ");
    const breakEven = panel.querySelector(".cold20-break-even");
    const baselineEdge = panel.querySelector(".cold20-baseline-edge");
    const ask = panel.querySelector(".cold20-ask");
    const payout = panel.querySelector(".cold20-payout");
    const note = panel.querySelector(".cold20-note");

    if (digit) digit.textContent = analysis?.candidate ?? "--";
    if (freq) freq.textContent = fmtPctOrDash(analysis?.cold_frequency_pct);
    if (hist) hist.textContent = fmtPctOrDash(analysis?.historical_differ_rate_pct);
    if (breakEven) breakEven.textContent = fmtPctOrDash(analysis?.break_even_probability_pct);
    if (baselineEdge) baselineEdge.textContent = fmtEdgeOrDash(analysis?.baseline_edge_vs_break_even_pp);
    if (ask) ask.textContent = fmtMoneyOrDash(analysis?.proposal_ask_price, analysis?.proposal_currency);
    if (payout) payout.textContent = fmtMoneyOrDash(analysis?.proposal_payout, analysis?.proposal_currency);
    if (note) {
      note.textContent = status === "READY"
        ? `Forward-test DIFFER ${analysis.candidate} for one tick. Do not call the ${fmtPctOrDash(analysis?.historical_differ_rate_pct)} historical rate a prediction probability; only resolved forward accuracy versus live break-even matters.`
        : status === "TIED_COLD_DIGITS"
          ? "Multiple digits are equally cold in the latest 20 ticks, so the strategy produces no candidate."
          : `Collecting the 20 displayed last digits required for this hypothesis: ${samples}/${required}.`;
    }
  }

  if (typeof updateMarket === "function") {
    const originalUpdateMarket = updateMarket;
    updateMarket = function proposalAwareUpdateMarket(symbol, market) {
      originalUpdateMarket(symbol, market);
      const card = typeof cards !== "undefined" ? cards.get(symbol) : null;
      updateProposalEdge(card, market);
      updateHot1000(card, market);
      updateColdReversion(card, market);
      updateCold20Differs(card, market);
    };
  }

  window.DSNPFXProposalEdgeUI = {
    updateProposalEdge,
    updateHot1000,
    updateColdReversion,
    updateCold20Differs,
  };
})();
