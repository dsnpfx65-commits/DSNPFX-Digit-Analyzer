(() => {
  "use strict";

  const SCAN_CYCLE_MS = 3600;
  const REVEAL_MS = 1650;

  function sampleState(card) {
    const trusted = card.querySelector(".trusted-samples")?.textContent || "0 / 100";
    const current = Number((trusted.match(/\d+/) || ["0"])[0]);
    return current < 100 ? "Learning" : "No Verified Match";
  }

  function scanCard(card, offset = 0) {
    if (!card || card.classList.contains("signal")) return;

    window.setTimeout(() => {
      if (card.classList.contains("signal")) return;

      const label = card.querySelector(".scanner-label");
      const digit = card.querySelector(".scanner-digit");
      const status = card.querySelector(".match-status");
      const note = card.querySelector(".scanner-note");

      card.classList.remove("revealed");
      if (digit) digit.textContent = "--";
      if (label) label.textContent = "SCANNING";
      if (status) status.textContent = "Analyzing";
      if (note) note.textContent = "Checking live production evidence";

      window.setTimeout(() => {
        if (card.classList.contains("signal")) return;
        card.classList.add("revealed");
        if (digit) digit.textContent = "--";
        if (label) label.textContent = "WAIT";
        if (status) status.textContent = sampleState(card);
        if (note) note.textContent = "No verified Match yet · scanning continues";
      }, REVEAL_MS);
    }, offset);
  }

  function runCycle() {
    const cards = [...document.querySelectorAll("#marketStack .market-card")];
    cards.forEach((card, index) => scanCard(card, index * 55));
  }

  function start() {
    runCycle();
    window.setInterval(runCycle, SCAN_CYCLE_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
