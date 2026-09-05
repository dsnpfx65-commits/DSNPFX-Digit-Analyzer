(() => {
  "use strict";

  // Scanner heartbeat only.
  // dashboard.js is the single owner of scanner DOM state and animation labels.
  // This helper only invalidates the scanner signature periodically so the
  // existing dashboard scanner starts a fresh visual scan cycle on the next
  // live websocket update. It never writes scanner text, digits, classes,
  // predictions, or verification state.
  const RESCAN_INTERVAL_MS = 2800;

  function requestRescan() {
    document.querySelectorAll("#marketStack .market-card").forEach((card) => {
      if (card.classList.contains("signal")) return;
      card._scannerSignature = null;
    });
  }

  function start() {
    requestRescan();
    window.setInterval(requestRescan, RESCAN_INTERVAL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
