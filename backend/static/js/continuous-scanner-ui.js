(() => {
  "use strict";

  // Visual research scanner. Production verification remains authoritative.
  // Unverified research candidates may be shown only as explicitly labelled
  // CANDIDATE telemetry; they are never labelled Match Found or promoted.
  const SCAN_MS = 2200;
  const REVEAL_MS = 1200;
  const FULL_ROTATION_MS = 1450;
  const phases = new WeakMap();

  function isVerified(card) {
    return Boolean(card && card.classList.contains("signal"));
  }

  function candidateDigit(card) {
    const value = card.querySelector(".candidate-digit")?.textContent?.trim();
    return /^[0-9]$/.test(value || "") ? value : null;
  }

  function trustedSamples(card) {
    const text = card.querySelector(".trusted-samples")?.textContent || "0 / 100";
    return Number((text.match(/\d+/) || ["0"])[0]);
  }

  function setScanning(card, now, index) {
    const label = card.querySelector(".scanner-label");
    const digit = card.querySelector(".scanner-digit");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");
    const sweep = card.querySelector(".scanner-sweep");
    const orb = card.querySelector(".scanner-orb");

    const angle = ((now % FULL_ROTATION_MS) / FULL_ROTATION_MS) * 360 + index * 9;
    if (sweep) {
      sweep.style.animation = "none";
      sweep.style.transform = `rotate(${angle}deg)`;
      sweep.style.opacity = "0.9";
    }
    if (orb) {
      const pulse = 0.18 + (Math.sin((now / 260) + index * 0.35) + 1) * 0.10;
      orb.style.boxShadow = `inset 0 0 32px rgba(33,243,138,.12), 0 0 38px rgba(33,243,138,${pulse.toFixed(3)})`;
    }

    card.classList.remove("revealed");
    if (label) label.textContent = "SCANNING";
    if (digit) digit.textContent = "--";
    if (status) status.textContent = "Analyzing live ticks";
    if (note) note.textContent = `Trusted evidence ${trustedSamples(card)}/100 · scanning`;
  }

  function setCandidateReveal(card) {
    const candidate = candidateDigit(card);
    const label = card.querySelector(".scanner-label");
    const digit = card.querySelector(".scanner-digit");
    const status = card.querySelector(".match-status");
    const note = card.querySelector(".scanner-note");
    const sweep = card.querySelector(".scanner-sweep");

    card.classList.add("revealed");
    if (sweep) sweep.style.opacity = "0.2";

    if (candidate !== null) {
      if (label) label.textContent = "CANDIDATE";
      if (digit) digit.textContent = candidate;
      if (status) status.textContent = "Research Candidate";
      if (note) note.textContent = "NOT VERIFIED · scanner will rescan";
    } else {
      if (label) label.textContent = "WAIT";
      if (digit) digit.textContent = "--";
      if (status) status.textContent = "No candidate yet";
      if (note) note.textContent = "Collecting more live evidence";
    }
  }

  function frame(now) {
    const cards = [...document.querySelectorAll("#marketStack .market-card")];

    cards.forEach((card, index) => {
      if (isVerified(card)) return;

      let state = phases.get(card);
      if (!state) {
        state = { phase: "scan", started: now + index * 90 };
        phases.set(card, state);
      }

      if (now < state.started) return;
      const elapsed = now - state.started;

      if (state.phase === "scan") {
        setScanning(card, now, index);
        if (elapsed >= SCAN_MS) {
          state.phase = "reveal";
          state.started = now;
          setCandidateReveal(card);
        }
      } else {
        setCandidateReveal(card);
        if (elapsed >= REVEAL_MS) {
          state.phase = "scan";
          state.started = now;
        }
      }
    });

    window.requestAnimationFrame(frame);
  }

  function start() {
    window.requestAnimationFrame(frame);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
