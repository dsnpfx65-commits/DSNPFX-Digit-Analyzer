(() => {
  "use strict";

  // Scanner text/reveal controller.
  // The visible radar sweep is intentionally owned by CSS so it keeps moving
  // even if websocket/model/research code throws or the JS event loop stalls.
  const SCAN_MS = 2200;
  const REVEAL_MS = 1100;

  function getCandidate(market) {
    const value = market?.candidate_prediction;
    return Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 9
      ? String(Number(value))
      : null;
  }

  function syncRevealedCandidate(card, market) {
    if (!card.classList.contains("revealed") || card.classList.contains("signal")) return;

    const digit = card.querySelector(".scanner-digit");
    const label = card.querySelector(".scanner-label");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");
    const candidate = getCandidate(market);

    if (candidate !== null) {
      if (digit) digit.textContent = candidate;
      if (label) label.textContent = "CANDIDATE";
      if (status) status.textContent = "Research Candidate";
      if (note) note.textContent = "NOT VERIFIED · scanning continues";
    } else {
      if (digit) digit.textContent = "--";
      if (label) label.textContent = "SCANNING";
      if (status) status.textContent = "Analyzing live ticks";
      if (note) note.textContent = "Collecting live evidence";
    }
  }

  function latestFor(card, fallback) {
    try {
      if (typeof latestMarkets !== "undefined") {
        return latestMarkets?.[card.dataset.symbol] || fallback || {};
      }
    } catch (_error) {
      // Fall back to the snapshot supplied by updateMarket.
    }
    return fallback || {};
  }

  function beginScan(card, market, verified) {
    const digit = card.querySelector(".scanner-digit");
    const label = card.querySelector(".scanner-label");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");

    clearTimeout(card._scanRevealTimer);
    clearTimeout(card._scanRestartTimer);
    card._scanRevealTimer = null;
    card._scanRestartTimer = null;
    card.classList.remove("revealed");

    if (digit) digit.textContent = "--";
    if (label) label.textContent = "SCANNING";
    if (status) status.textContent = "Analyzing live ticks";
    if (note) note.textContent = "Checking live evidence";

    card._scanRevealTimer = window.setTimeout(() => {
      card._scanRevealTimer = null;
      card.classList.add("revealed");

      const latest = latestFor(card, market);
      const latestVerified = Boolean(
        latest?.is_premium
        && latest?.published_prediction !== null
        && latest?.published_prediction !== undefined
      );

      if (latestVerified) {
        if (digit) digit.textContent = typeof safeText === "function"
          ? safeText(latest?.published_prediction)
          : String(latest?.published_prediction ?? "--");
        if (label) label.textContent = "PREDICTION";
        if (status) status.textContent = "Match Found";
        if (note) note.textContent = typeof evidenceNote === "function"
          ? evidenceNote(latest, true)
          : "Verified production evidence";
      } else {
        syncRevealedCandidate(card, latest);
      }

      card._scanRestartTimer = window.setTimeout(() => {
        card._scanRestartTimer = null;
        const newest = latestFor(card, latest);
        const newestVerified = Boolean(
          newest?.is_premium
          && newest?.published_prediction !== null
          && newest?.published_prediction !== undefined
        );
        beginScan(card, newest, newestVerified);
      }, REVEAL_MS);
    }, SCAN_MS);
  }

  // Replace dashboard.js scanner binding. This controller never manipulates
  // .scanner-sweep animation; dashboard.css owns the infinite radar motion.
  updateScanner = function updateScannerAllMarkets(card, market, verified) {
    try {
      if (typeof scannerSignature === "function") {
        card._scannerSignature = scannerSignature(market, verified);
      }

      if (!verified) syncRevealedCandidate(card, market);

      if (!card._scanRevealTimer && !card._scanRestartTimer) {
        beginScan(card, market, verified);
      }
    } catch (error) {
      console.warn("Scanner controller update failed", card?.dataset?.symbol, error);
      // CSS radar animation continues independently even if this reveal logic fails.
    }
  };
})();
