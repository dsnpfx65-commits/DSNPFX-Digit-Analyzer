(() => {
  "use strict";

  // Self-healing scanner controller. The scanner must keep cycling even if
  // another dashboard extension throws or updateMarket is temporarily skipped.
  const SCAN_MS = 2200;
  const REVEAL_MS = 1100;
  const ROTATION_MS = 1350;
  const WATCHDOG_MS = 750;

  function getCandidate(market) {
    const value = market?.candidate_prediction;
    const n = Number(value);
    return Number.isInteger(n) && n >= 0 && n <= 9 ? String(n) : null;
  }

  function safeLatest(card, fallback = {}) {
    try {
      if (typeof latestMarkets !== "undefined" && latestMarkets && typeof latestMarkets === "object") {
        return latestMarkets[card.dataset.symbol] || fallback || {};
      }
    } catch (_error) {}
    return fallback || {};
  }

  function isVerified(market) {
    return Boolean(
      market?.is_premium
      && market?.published_prediction !== null
      && market?.published_prediction !== undefined
    );
  }

  function setScanningText(card) {
    const digit = card.querySelector(".scanner-digit");
    const label = card.querySelector(".scanner-label");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");
    if (digit) digit.textContent = "--";
    if (label) label.textContent = "SCANNING";
    if (status) status.textContent = "Analyzing live ticks";
    if (note) note.textContent = "Checking live evidence";
  }

  function reveal(card, market) {
    const latest = safeLatest(card, market);
    const digit = card.querySelector(".scanner-digit");
    const label = card.querySelector(".scanner-label");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");

    card.classList.add("revealed");

    if (isVerified(latest)) {
      if (digit) digit.textContent = String(latest.published_prediction);
      if (label) label.textContent = "PREDICTION";
      if (status) status.textContent = "Match Found";
      if (note) note.textContent = typeof evidenceNote === "function"
        ? evidenceNote(latest, true)
        : "Verified production evidence";
      return;
    }

    const candidate = getCandidate(latest);
    if (candidate !== null) {
      if (digit) digit.textContent = candidate;
      if (label) label.textContent = "CANDIDATE";
      if (status) status.textContent = "Research Candidate";
      if (note) note.textContent = "NOT VERIFIED · rescanning";
    } else {
      if (digit) digit.textContent = "--";
      if (label) label.textContent = "SCANNING";
      if (status) status.textContent = "Analyzing live ticks";
      if (note) note.textContent = "Collecting live evidence";
    }
  }

  function beginScan(card, market = {}) {
    if (!card || !card.isConnected) return;

    clearTimeout(card._scanRevealTimer);
    clearTimeout(card._scanRestartTimer);
    card._scanRevealTimer = null;
    card._scanRestartTimer = null;
    card.classList.remove("revealed");
    setScanningText(card);

    card._scanRevealTimer = window.setTimeout(() => {
      card._scanRevealTimer = null;
      if (!card.isConnected) return;
      reveal(card, market);

      card._scanRestartTimer = window.setTimeout(() => {
        card._scanRestartTimer = null;
        if (!card.isConnected) return;
        beginScan(card, safeLatest(card, market));
      }, REVEAL_MS);
    }, SCAN_MS);
  }

  function animateScannerSweeps(now) {
    try {
      const marketCards = document.querySelectorAll("#marketStack .market-card");
      const baseAngle = ((now % ROTATION_MS) / ROTATION_MS) * 360;

      marketCards.forEach((card, index) => {
        const sweep = card.querySelector(".scanner-sweep");
        const orb = card.querySelector(".scanner-orb");
        if (sweep) {
          sweep.style.animation = "none";
          sweep.style.transform = `rotate(${baseAngle + index * 17}deg)`;
          sweep.style.opacity = card.classList.contains("revealed") ? "0.35" : "0.92";
        }
        if (orb) {
          const pulse = 0.17 + (Math.sin(now / 260 + index * 0.4) + 1) * 0.09;
          orb.style.boxShadow = `inset 0 0 30px rgba(33,243,138,.12),0 0 38px rgba(33,243,138,${pulse.toFixed(3)})`;
        }
      });
    } catch (error) {
      console.warn("Scanner animation frame failed", error);
    }
    window.requestAnimationFrame(animateScannerSweeps);
  }

  // Dashboard hook. Keep it small so other UI modules cannot control the
  // scanner lifecycle.
  updateScanner = function updateScannerSelfHealing(card, market, verified) {
    try {
      card._scannerSignature = typeof scannerSignature === "function"
        ? scannerSignature(market, verified)
        : `${card.dataset.symbol}:${verified}:${market?.candidate_prediction ?? ""}`;

      if (!card._scanRevealTimer && !card._scanRestartTimer) {
        beginScan(card, market || {});
      }
    } catch (error) {
      console.warn("Scanner update hook failed", card?.dataset?.symbol, error);
    }
  };

  // Independent watchdog: if updateMarket/model-comparison/proposal UI throws,
  // every existing market card still gets its scanner started or restarted.
  function watchdog() {
    try {
      document.querySelectorAll("#marketStack .market-card").forEach((card) => {
        if (!card._scanRevealTimer && !card._scanRestartTimer) {
          beginScan(card, safeLatest(card, {}));
        }
      });
    } catch (error) {
      console.warn("Scanner watchdog failed", error);
    }
  }

  window.requestAnimationFrame(animateScannerSweeps);
  window.setInterval(watchdog, WATCHDOG_MS);
  window.setTimeout(watchdog, 250);
})();
