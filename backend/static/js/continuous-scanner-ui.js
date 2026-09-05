(() => {
  "use strict";

  // Visual-only scanner heartbeat. The backend remains the authority for
  // verified signals; this file never creates or promotes a prediction.
  const STATUS_STEP_MS = 450;
  const FULL_ROTATION_MS = 1550;
  let lastStatusStep = 0;
  let statusPhase = 0;

  function isVerified(card) {
    return Boolean(card && card.classList.contains("signal"));
  }

  function learningState(card) {
    const trusted = card.querySelector(".trusted-samples")?.textContent || "0 / 100";
    const current = Number((trusted.match(/\d+/) || ["0"])[0]);
    return current < 100 ? `Learning ${current}/100` : "No Verified Match";
  }

  function animateFrame(now) {
    const cards = document.querySelectorAll("#marketStack .market-card");
    const angle = ((now % FULL_ROTATION_MS) / FULL_ROTATION_MS) * 360;

    cards.forEach((card, index) => {
      if (isVerified(card)) return;

      const sweep = card.querySelector(".scanner-sweep");
      const orb = card.querySelector(".scanner-orb");
      if (sweep) {
        // Force a live transform from JS so scanner motion remains visible even
        // if a browser pauses/restarts the CSS animation after DOM updates.
        sweep.style.animation = "none";
        sweep.style.transform = `rotate(${angle + index * 7}deg)`;
        sweep.style.opacity = "0.72";
      }
      if (orb) {
        const pulse = 0.16 + (Math.sin((now / 330) + index * 0.3) + 1) * 0.08;
        orb.style.boxShadow = `inset 0 0 28px rgba(33,243,138,.10), 0 0 34px rgba(33,243,138,${pulse.toFixed(3)})`;
      }
    });

    if (now - lastStatusStep >= STATUS_STEP_MS) {
      lastStatusStep = now;
      statusPhase = (statusPhase + 1) % 4;
      const dots = ".".repeat(statusPhase);

      cards.forEach((card) => {
        if (isVerified(card)) return;
        const label = card.querySelector(".scanner-label");
        const digit = card.querySelector(".scanner-digit");
        const status = card.querySelector(".match-status");
        const note = card.querySelector(".scanner-note");

        // Keep the unverified scanner visually active. Never expose a research
        // candidate as the scanner digit.
        card.classList.remove("revealed");
        if (digit) digit.textContent = "--";
        if (label) label.textContent = `SCANNING${dots}`;
        if (status) status.textContent = "Analyzing live ticks";
        if (note) note.textContent = `${learningState(card)} · evidence gate active`;
      });
    }

    window.requestAnimationFrame(animateFrame);
  }

  function start() {
    window.requestAnimationFrame(animateFrame);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
