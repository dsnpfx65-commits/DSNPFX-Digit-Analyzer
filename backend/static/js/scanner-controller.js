(() => {
  "use strict";

  // One controller owns every Market Insight scanner.
  // All market orbs sweep continuously and independently. The reveal phase
  // never stops the visual scanner; only verified production output may use
  // the Match Found label.
  const SCAN_MS = 2200;
  const REVEAL_MS = 1100;
  const ROTATION_MS = 1350;

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

  function animateScannerSweeps(now) {
    const marketCards = document.querySelectorAll("#marketStack .market-card");
    const baseAngle = ((now % ROTATION_MS) / ROTATION_MS) * 360;

    marketCards.forEach((card, index) => {
      const sweep = card.querySelector(".scanner-sweep");
      const orb = card.querySelector(".scanner-orb");

      // Never stop a market's visible sweep. Verified cards may reveal a
      // production digit, but the radar itself still scans the live feed.
      if (sweep) {
        sweep.style.animation = "none";
        sweep.style.transform = `rotate(${baseAngle + index * 17}deg)`;
        sweep.style.opacity = "0.92";
      }

      if (orb) {
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

    // Every market uses the same scan duration. We deliberately removed the
    // per-card stagger so all 13 Volatility markets visibly scan together.
    card._scanRevealTimer = window.setTimeout(() => {
      card._scanRevealTimer = null;
      card.classList.add("revealed");

      const latest = latestMarkets?.[card.dataset.symbol] || market || {};
      const latestVerified = Boolean(
        latest?.is_premium
        && latest?.published_prediction !== null
        && latest?.published_prediction !== undefined
      );

      if (latestVerified) {
        if (digit) digit.textContent = safeText(latest?.published_prediction);
        if (label) label.textContent = "PREDICTION";
        if (status) status.textContent = "Match Found";
        if (note) note.textContent = evidenceNote(latest, true);
      } else {
        syncRevealedCandidate(card, latest);
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
    }, SCAN_MS);
  }

  // Replace dashboard.js scanner binding with the all-market controller.
  updateScanner = function updateScannerAllMarkets(card, market, verified) {
    const signature = scannerSignature(market, verified);
    card._scannerSignature = signature;

    // Keep a revealed research digit synchronized to V9 without interrupting
    // the scanner cycle or restarting timers on every websocket update.
    if (!verified) syncRevealedCandidate(card, market);

    if (!card._scanRevealTimer && !card._scanRestartTimer) {
      beginScan(card, market, verified);
    }
  };

  window.requestAnimationFrame(animateScannerSweeps);
})();
