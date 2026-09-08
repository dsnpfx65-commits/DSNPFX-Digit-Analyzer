(() => {
  "use strict";

  // V10 scanner controller.
  // Only the published, production-approved Adaptive Forward Ensemble digit may
  // ever be revealed in the main scanner. Research candidates stay in the
  // evidence panels and are never rendered inside the prediction orb.
  const SCAN_MS = 2200;
  const REVEAL_MS = 1100;
  const CARD_STAGGER_MS = 70;
  const ROTATION_MS = 1350;

  function animateScannerSweeps(now) {
    const cards = document.querySelectorAll("#marketStack .market-card");
    const baseAngle = ((now % ROTATION_MS) / ROTATION_MS) * 360;

    cards.forEach((card, index) => {
      if (card.classList.contains("signal") && card.classList.contains("revealed")) return;

      const sweep = card.querySelector(".scanner-sweep");
      const orb = card.querySelector(".scanner-orb");
      if (sweep) {
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

  function isVerified(market) {
    return Boolean(
      market?.is_premium
      && market?.published_prediction !== null
      && market?.published_prediction !== undefined
    );
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
    if (note) note.textContent = "Checking V10 adaptive evidence";

    const index = Math.max(0, currentOrder.indexOf(card.dataset.symbol));
    const delay = SCAN_MS + index * CARD_STAGGER_MS;

    card._scanRevealTimer = window.setTimeout(() => {
      card._scanRevealTimer = null;
      card.classList.add("revealed");

      const latest = latestMarkets?.[card.dataset.symbol] || market || {};
      const latestVerified = isVerified(latest);

      if (verified && latestVerified) {
        if (digit) digit.textContent = safeText(latest.published_prediction);
        if (label) label.textContent = "PREDICTION";
        if (status) status.textContent = "Match Found";
        if (note) note.textContent = evidenceNote(latest, true);
        return;
      }

      // V10 abstains when the adaptive authority has not passed every gate.
      // Do not substitute research_candidate, candidate_prediction, proposal
      // best digit, HOT/COLD, or any legacy model vote here.
      if (digit) digit.textContent = "--";
      if (label) label.textContent = "WAIT";
      if (status) status.textContent = "No Verified Prediction";
      if (note) note.textContent = "Adaptive authority has not qualified a digit · rescanning";

      card._scanRestartTimer = window.setTimeout(() => {
        card._scanRestartTimer = null;
        const newest = latestMarkets?.[card.dataset.symbol] || latest || {};
        beginScan(card, newest, isVerified(newest));
      }, REVEAL_MS);
    }, delay);
  }

  // Replace dashboard.js scanner binding with the V10 single-authority scanner.
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
