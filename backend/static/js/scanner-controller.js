(() => {
  "use strict";

  // Single scanner owner for Market Insight.
  // Production verification remains authoritative. Research candidates are
  // clearly labelled and can never be shown as Match Found.
  const SCAN_MS = 2200;
  const REVEAL_MS = 1100;
  const CARD_STAGGER_MS = 70;
  const ROTATION_MS = 1350;

  function getCandidate(market) {
    const value = market?.candidate_prediction;
    return Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 9
      ? String(Number(value))
      : null;
  }

  function animateScannerSweeps(now) {
    const cards = document.querySelectorAll("#marketStack .market-card");
    const baseAngle = ((now % ROTATION_MS) / ROTATION_MS) * 360;

    cards.forEach((card, index) => {
      if (card.classList.contains("signal") && card.classList.contains("revealed")) return;

      const sweep = card.querySelector(".scanner-sweep");
      const orb = card.querySelector(".scanner-orb");
      if (sweep) {
        // JS drives the visible sweep directly. Do not rely on CSS animation.
        sweep.style.animation = "none";
        sweep.style.transform = `rotate(${baseAngle + index * 11}deg)`;
        sweep.style.opacity = card.classList.contains("revealed") ? "0.28" : "0.92";
      }
      if (orb && !card.classList.contains("revealed")) {
        const pulse = 0.17 + (Math.sin(now / 260 + index * 0.4) + 1) * 0.09;
        orb.style.boxShadow = `inset 0 0 30px rgba(33,243,138,.12),0 0 38px rgba(33,243,138,${pulse.toFixed(3)})`;
      }
    });

    window.requestAnimationFrame(animateScannerSweeps);
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

    const index = Math.max(0, currentOrder.indexOf(card.dataset.symbol));
    const delay = SCAN_MS + index * CARD_STAGGER_MS;

    card._scanRevealTimer = window.setTimeout(() => {
      card._scanRevealTimer = null;
      card.classList.add("revealed");

      if (verified) {
        if (digit) digit.textContent = safeText(market?.published_prediction);
        if (label) label.textContent = "PREDICTION";
        if (status) status.textContent = "Match Found";
        if (note) note.textContent = evidenceNote(market, true);
        return;
      }

      const latest = latestMarkets?.[card.dataset.symbol] || market || {};
      const candidate = getCandidate(latest);
      if (candidate !== null) {
        if (digit) digit.textContent = candidate;
        if (label) label.textContent = "CANDIDATE";
        if (status) status.textContent = "Research Candidate";
        if (note) note.textContent = "NOT VERIFIED · rescanning";
      } else {
        if (digit) digit.textContent = "--";
        if (label) label.textContent = "WAIT";
        if (status) status.textContent = "No candidate yet";
        if (note) note.textContent = "Collecting live evidence · rescanning";
      }

      card._scanRestartTimer = window.setTimeout(() => {
        card._scanRestartTimer = null;
        const newest = latestMarkets?.[card.dataset.symbol] || latest || {};
        const newestVerified = Boolean(
          newest?.is_premium
          && newest?.published_prediction !== null
          && newest?.published_prediction !== undefined
        );
        beginScan(card, newest, newestVerified);
      }, REVEAL_MS);
    }, delay);
  }

  // Replace dashboard.js scanner binding with this one scanner controller.
  updateScanner = function updateScannerSingle(card, market, verified) {
    const signature = scannerSignature(market, verified);

    if (verified) {
      if (card._scannerSignature === signature && card.classList.contains("revealed")) {
        const note = card.querySelector(".scanner-note");
        if (note) note.textContent = evidenceNote(market, true);
        return;
      }
      card._scannerSignature = signature;
      beginScan(card, market, true);
      return;
    }

    card._scannerSignature = signature;
    if (!card._scanRevealTimer && !card._scanRestartTimer) {
      beginScan(card, market, false);
    }
  };

  window.requestAnimationFrame(animateScannerSweeps);
})();
