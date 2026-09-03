(() => {
  const fmtPct = (value) => (
    value === null || value === undefined || Number.isNaN(Number(value))
      ? "--"
      : `${Number(value).toFixed(2)}%`
  );

  const fmtEdge = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
    const number = Number(value);
    return `${number >= 0 ? "+" : ""}${number.toFixed(2)} pp`;
  };

  function cold20Analysis(market) {
    const metadata = market?.model_metadata;
    if (!metadata || typeof metadata !== "object") return {};
    const analysis = metadata.cold_20_differs;
    return analysis && typeof analysis === "object" ? analysis : {};
  }

  function forwardEvidence(analysis) {
    const evidence = analysis?.forward_evidence;
    return evidence && typeof evidence === "object" ? evidence : {};
  }

  function ensureForwardPanel(card) {
    if (!card) return null;
    const cold20 = card.querySelector(".cold20-differs-panel");
    if (!cold20) return null;

    let panel = cold20.querySelector(".cold20-forward-evidence");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.className = "cold20-forward-evidence";
    panel.innerHTML = `
      <div class="model-votes">
        <span>COLD 20 FORWARD EVIDENCE · PROSPECTIVE ONLY</span>
        <strong class="cold20-forward-decision">NO VERIFIED EDGE</strong>
      </div>
      <div class="v9-grid cold20-forward-grid">
        <div><span>Forward Samples</span><strong class="cold20-forward-samples">0</strong></div>
        <div><span>Forward Accuracy</span><strong class="cold20-forward-accuracy">--</strong></div>
        <div><span>95% Lower Bound</span><strong class="cold20-forward-lower">--</strong></div>
        <div><span>Natural Differ Baseline</span><strong>90.00%</strong></div>
        <div><span>Avg Recorded Break-even</span><strong class="cold20-forward-break-even">--</strong></div>
        <div><span>Forward Edge vs Break-even</span><strong class="cold20-forward-edge">--</strong></div>
        <div><span>Wins</span><strong class="cold20-forward-wins">0</strong></div>
        <div><span>Losses</span><strong class="cold20-forward-losses">0</strong></div>
        <div><span>Pending</span><strong class="cold20-forward-pending">0</strong></div>
      </div>
      <div class="gate-blocker">
        <span>Evidence Rule</span>
        <strong class="cold20-forward-note">Only predictions recorded before a later tick are counted. Evidence Edge requires at least 100 resolved samples and the 95% lower confidence bound to exceed both the natural 90% DIFFER baseline and recorded proposal break-even.</strong>
      </div>`;

    cold20.appendChild(panel);
    return panel;
  }

  function updateForwardEvidence(card, market) {
    const panel = ensureForwardPanel(card);
    if (!panel) return;

    const analysis = cold20Analysis(market);
    const evidence = forwardEvidence(analysis);

    const samples = Number(
      analysis?.forward_samples ?? evidence?.resolved ?? 0
    );
    const accuracy = analysis?.forward_accuracy_pct ?? evidence?.forward_accuracy_pct;
    const lower = analysis?.forward_lower_95_pct ?? evidence?.lower_95_pct;
    const averageBreakEven = analysis?.forward_average_break_even_pct
      ?? evidence?.average_recorded_break_even_pct;
    const edge = analysis?.forward_edge_vs_break_even_pp
      ?? evidence?.edge_vs_average_break_even_pp;
    const decision = String(
      analysis?.forward_decision ?? evidence?.decision ?? "NO_VERIFIED_EDGE"
    ).toUpperCase();

    const label = decision === "EVIDENCE_EDGE" ? "EVIDENCE EDGE" : "NO VERIFIED EDGE";

    panel.querySelector(".cold20-forward-samples").textContent = String(samples);
    panel.querySelector(".cold20-forward-accuracy").textContent = fmtPct(accuracy);
    panel.querySelector(".cold20-forward-lower").textContent = fmtPct(lower);
    panel.querySelector(".cold20-forward-break-even").textContent = fmtPct(averageBreakEven);
    panel.querySelector(".cold20-forward-edge").textContent = fmtEdge(edge);
    panel.querySelector(".cold20-forward-wins").textContent = String(Number(evidence?.wins || 0));
    panel.querySelector(".cold20-forward-losses").textContent = String(Number(evidence?.losses || 0));
    panel.querySelector(".cold20-forward-pending").textContent = String(Number(evidence?.pending || 0));
    panel.querySelector(".cold20-forward-decision").textContent = label;

    const note = panel.querySelector(".cold20-forward-note");
    if (note) {
      if (samples < 100) {
        note.textContent = `Prospective evidence is still building: ${samples}/100 resolved samples. No promotion is allowed from historical 20-tick frequency alone.`;
      } else if (decision === "EVIDENCE_EDGE") {
        note.textContent = "Forward evidence currently clears the research threshold: the 95% lower confidence bound exceeds both 90% and the average recorded live break-even. This remains research evidence and does not bypass the production Match gate.";
      } else {
        note.textContent = "At least 100 outcomes exist, but the confidence-bound test has not verified edge over both the 90% natural DIFFER baseline and recorded break-even.";
      }
    }
  }

  if (typeof updateMarket === "function") {
    const originalUpdateMarket = updateMarket;
    updateMarket = function cold20ForwardAwareUpdateMarket(symbol, market) {
      originalUpdateMarket(symbol, market);
      const card = typeof cards !== "undefined" ? cards.get(symbol) : null;
      updateForwardEvidence(card, market);
    };
  }

  window.DSNPFXCold20ForwardUI = { updateForwardEvidence };
})();
