(() => {
  "use strict";

  // Single active scanner controller for Market Insight.
  // It replaces dashboard.js's original updateScanner binding before async
  // state/websocket payloads are rendered. Production verification remains
  // authoritative: only verified markets can display Match Found.
  const SCAN_MS = 2200;
  const REVEAL_MS = 1100;
  const CARD_STAGGER_MS = 70;

  function getCandidate(market) {
    const value = market?.candidate_prediction;
    return Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 9
      ? String(Number(value))
      : null;
  }

  function beginScan(card, market, verified) {
    const digit = card.querySelector(".scanner-digit");
    const label = card.querySelector(".scanner-label");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");

    clearTimeout(card._scanRevealTimer);
    clearTimeout(card._scanRestartTimer);
    card.classList.remove("revealed");

    if (digit) digit.textContent = "--";
    if (label) label.textContent = "SCANNING";
    if (status) status.textContent = "Analyzing live ticks";
    if (note) note.textContent = "Checking live evidence";

    const index = Math.max(0, currentOrder.indexOf(card.dataset.symbol));
    const delay = SCAN_MS + index * CARD_STAGGER_MS;

    card._scanRevealTimer = window.setTimeout(() => {
      card.classList.add("revealed");

      if (verified) {
        if (digit) digit.textContent = safeText(market?.published_prediction);
        if (label) label.textContent = "PREDICTION";
        if (status) status.textContent = "Match Found";
        if (note) note.textContent = evidenceNote(market, true);
        return;
      }

      const candidate = getCandidate(market);
      if (candidate !== null) {
        if (digit) digit.textContent = candidate;
        if (label) label.textContent = "CANDIDATE";
        if (status) status.textContent = "Research Candidate";
        if (note) note.textContent = "NOT VERIFIED · rescanning";
      } else {
        if (digit) digit.textContent = "--";
        if (label) label.textContent = "WAIT";
        if (status) status.textContent = Number(market?.rolling_samples || 0) < PRODUCTION_THRESHOLDS.samples
          ? "Learning"
          : "No Verified Match";
        if (note) note.textContent = evidenceNote(market, false);
      }

      card._scanRestartTimer = window.setTimeout(() => {
        const latest = latestMarkets?.[card.dataset.symbol] || market || {};
        const latestVerified = Boolean(
          latest?.is_premium
          && latest?.published_prediction !== null
          && latest?.published_prediction !== undefined
        );
        beginScan(card, latest, latestVerified);
      }, REVEAL_MS);
    }, delay);
  }

  // Replace the original dashboard scanner function with one controller.
  updateScanner = function updateScannerSingle(card, market, verified) {
    const signature = scannerSignature(market, verified);

    if (verified) {
      // Restart only when the verified payload changes; otherwise keep the
      // verified result stable on screen.
      if (card._scannerSignature === signature && card.classList.contains("revealed")) {
        const note = card.querySelector(".scanner-note");
        if (note) note.textContent = evidenceNote(market, true);
        return;
      }
      card._scannerSignature = signature;
      beginScan(card, market, true);
      return;
    }

    // For unverified markets the scanner intentionally cycles forever, using
    // the newest market snapshot whenever each cycle restarts.
    card._scannerSignature = signature;
    if (!card._scanRevealTimer && !card._scanRestartTimer) {
      beginScan(card, market, false);
    }
  };
})();
