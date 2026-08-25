(() => {
  const fmtPct = (value) => (
    value === null || value === undefined || Number.isNaN(Number(value))
      ? "--"
      : `${Number(value).toFixed(2)}%`
  );

  const fmtSignedPp = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
    const number = Number(value);
    return `${number >= 0 ? "+" : ""}${number.toFixed(2)} pp`;
  };

  function metadata(market) {
    return market?.model_metadata && typeof market.model_metadata === "object"
      ? market.model_metadata
      : {};
  }

  function ensureResearchRows(card) {
    if (!card || card.querySelector(".hot1000-candidate")) return;
    const grid = card.querySelector(".v9-grid");
    if (!grid) return;

    const rows = [
      ["HOT 1000", "hot1000-candidate"],
      ["HOT 1000 Frequency", "hot1000-frequency"],
      ["COLD 200", "cold200-candidate"],
      ["COLD 500", "cold500-candidate"],
      ["COLD 1000", "cold1000-candidate"],
      ["HOT vs COLD", "hot-cold-comparison"],
    ];

    rows.forEach(([label, className]) => {
      const wrapper = document.createElement("div");
      const span = document.createElement("span");
      const strong = document.createElement("strong");
      span.textContent = label;
      strong.className = className;
      strong.textContent = "--";
      wrapper.append(span, strong);
      grid.appendChild(wrapper);
    });
  }

  function windowReport(cold, window) {
    const windows = cold?.windows;
    if (!windows || typeof windows !== "object") return {};
    return windows[window] || windows[String(window)] || {};
  }

  function candidateLabel(report, mode) {
    if (!report || report.candidate === null || report.candidate === undefined) {
      if (String(report?.status || "").includes("TIED")) return "TIED · WAIT";
      return "COLLECTING";
    }

    const frequency = fmtPct(report.frequency_pct);
    const deviation = fmtSignedPp(report.deviation_vs_10pct_pp);
    return `${mode} ${report.candidate} · ${frequency} · ${deviation}`;
  }

  function updateFrequencyResearch(card, market) {
    if (!card) return;
    ensureResearchRows(card);

    const meta = metadata(market);
    const hot = meta.hot_1000_continuation || {};
    const cold = meta.cold_reversion || {};
    const cold200 = windowReport(cold, 200);
    const cold500 = windowReport(cold, 500);
    const cold1000 = windowReport(cold, 1000);

    const hotCandidate = card.querySelector(".hot1000-candidate");
    const hotFrequency = card.querySelector(".hot1000-frequency");
    const cold200Node = card.querySelector(".cold200-candidate");
    const cold500Node = card.querySelector(".cold500-candidate");
    const cold1000Node = card.querySelector(".cold1000-candidate");
    const comparison = card.querySelector(".hot-cold-comparison");

    if (hotCandidate) hotCandidate.textContent = candidateLabel(hot, "MATCH");
    if (hotFrequency) {
      hotFrequency.textContent = hot.candidate === null || hot.candidate === undefined
        ? `${hot.samples || 0}/${hot.samples_required || 1000} ticks`
        : `Z ${Number(hot.z_score || 0).toFixed(2)} · windows ${Number(hot.agreeing_windows || 0)}/${Number(hot.completed_diagnostic_windows || 0)}`;
    }
    if (cold200Node) cold200Node.textContent = candidateLabel(cold200, "MATCH");
    if (cold500Node) cold500Node.textContent = candidateLabel(cold500, "MATCH");
    if (cold1000Node) cold1000Node.textContent = candidateLabel(cold1000, "MATCH");

    if (comparison) {
      const hotDigit = hot?.candidate;
      const coldDigit = cold1000?.candidate ?? cold500?.candidate ?? cold200?.candidate;
      if (hotDigit === null || hotDigit === undefined || coldDigit === null || coldDigit === undefined) {
        comparison.textContent = "Collecting independent evidence";
      } else if (Number(hotDigit) === Number(coldDigit)) {
        comparison.textContent = `Same digit ${hotDigit} · conflicting hypotheses`;
      } else {
        comparison.textContent = `HOT ${hotDigit} vs COLD ${coldDigit} · forward test only`;
      }
    }
  }

  if (typeof updateMarket === "function") {
    const originalUpdateMarket = updateMarket;
    updateMarket = function frequencyResearchAwareUpdateMarket(symbol, market) {
      originalUpdateMarket(symbol, market);
      const card = typeof cards !== "undefined" ? cards.get(symbol) : null;
      updateFrequencyResearch(card, market);
    };
  }

  window.DSNPFXFrequencyResearchUI = { updateFrequencyResearch };
})();
