(() => {
  "use strict";

  const text = (selector, value, root = document) => {
    const node = root.querySelector(selector);
    if (node) node.textContent = value;
    return node;
  };

  function relabelStaticShell() {
    const introEyebrow = document.querySelector(".intro-card .eyebrow");
    if (introEyebrow) introEyebrow.textContent = "Live Market Scanner · V10 Adaptive Forward Ensemble";

    const introCopy = document.querySelector(".intro-card .intro-copy");
    if (introCopy) {
      introCopy.textContent = "Every supported Volatility market is scanned continuously from the Deriv Options / Digits tick feed. V10 allows only the Adaptive Forward Ensemble to select the authoritative Match digit. The scanner reveals a digit only after the production evidence gate approves it. All other model digits remain research evidence only.";
    }

    document.querySelectorAll(".heading-meta .research-badge").forEach((badge) => {
      if (badge.textContent.includes("Candidate")) badge.textContent = "One Authority · Adaptive Forward";
    });

    const evidenceEyebrow = document.querySelector(".evidence-watch-heading .eyebrow");
    if (evidenceEyebrow) evidenceEyebrow.textContent = "V10 Forward Evidence Watch";
  }

  function relabelCard(card, market = {}) {
    if (!card) return;

    const candidate = market?.candidate_prediction;
    const published = market?.published_prediction;
    const isVerified = Boolean(market?.is_premium && published !== null && published !== undefined);
    const hasAuthority = candidate !== null && candidate !== undefined;

    const regimeSmall = card.querySelector(".market-tick-row > div:nth-child(3) small");
    if (regimeSmall) regimeSmall.textContent = "V10 analysis";

    const candidateLabel = card.querySelector(".candidate-strip > div:first-child span");
    if (candidateLabel) candidateLabel.textContent = "V10 Adaptive Authority";

    const candidateDigit = card.querySelector(".candidate-digit");
    if (candidateDigit) candidateDigit.textContent = hasAuthority ? String(candidate) : "--";

    const warning = card.querySelector(".candidate-warning");
    if (warning) {
      if (isVerified) {
        warning.textContent = "Verified V10 Match signal — adaptive authority and production gate approved.";
      } else if (hasAuthority) {
        warning.textContent = "V10 selected one forward-verified digit, but the production gate has not approved a trade signal.";
      } else {
        warning.textContent = "No forward-verified adaptive prediction yet — research models cannot publish a digit.";
      }
    }

    const details = card.querySelector(".v9-details");
    if (details) {
      const summary = details.querySelector(":scope > summary");
      if (summary) summary.textContent = "Research Models · Evidence Only";
    }

    const proposalLabel = card.querySelector(".proposal-best-digit")?.parentElement?.querySelector("span");
    if (proposalLabel) proposalLabel.textContent = "Research Best Match";

    const proposalHeadingSmall = card.querySelector(".proposal-edge-heading small");
    if (proposalHeadingSmall) proposalHeadingSmall.textContent = "Research only · never becomes the published digit directly";

    const modelVotesLabel = card.querySelector(".model-votes > span");
    if (modelVotesLabel && modelVotesLabel.textContent === "Voting Models") {
      modelVotesLabel.textContent = "Research Model Votes";
    }

    const confidenceLabel = card.querySelector(".verified-confidence")?.parentElement?.querySelector("span");
    if (confidenceLabel) confidenceLabel.textContent = "Production Evidence Confidence";
  }

  function relabelAllCards() {
    document.querySelectorAll(".market-card").forEach((card) => {
      const symbol = card.dataset.symbol;
      const market = (typeof latestMarkets === "object" && latestMarkets && symbol)
        ? (latestMarkets[symbol] || {})
        : {};
      relabelCard(card, market);
    });
  }

  relabelStaticShell();

  if (typeof window.updateMarket === "function") {
    const baseUpdateMarket = window.updateMarket;
    window.updateMarket = function dsnpfxV10UpdateMarket(symbol, market) {
      const result = baseUpdateMarket(symbol, market);
      const card = (typeof cards !== "undefined" && cards?.get) ? cards.get(symbol) : document.querySelector(`.market-card[data-symbol="${symbol}"]`);
      relabelCard(card, market || {});
      return result;
    };
  }

  if (typeof window.applyPayload === "function") {
    const baseApplyPayload = window.applyPayload;
    window.applyPayload = function dsnpfxV10ApplyPayload(payload) {
      const result = baseApplyPayload(payload);
      relabelAllCards();
      return result;
    };
  }

  document.addEventListener("DOMContentLoaded", () => {
    relabelStaticShell();
    relabelAllCards();
  });

  setTimeout(relabelAllCards, 0);
})();
