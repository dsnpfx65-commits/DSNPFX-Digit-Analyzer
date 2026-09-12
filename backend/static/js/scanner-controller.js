(() => {
  "use strict";

  // DSNPFX V12 precision next-tick trial scanner.
  //
  // Goal:
  //   PRECISION TEST -> next Deriv tick -> exact last digit -> MATCH/WIN or MISS/LOSS.
  //
  // Raw model votes are deliberately excluded. A browser trial is created only
  // when the backend V12 precision selector has an independently validated
  // conditional edge confirming the adaptive candidate. Production-approved
  // predictions still take priority.

  const WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public";
  const ROTATION_MS = 1350;
  const RESULT_HOLD_MS = 1800;
  const RECONNECT_MS = 1800;

  const directTicks = new Map();
  const trialCandidates = new Map();
  const trials = new Map();
  const subscribed = new Set();
  const trialStats = new Map();

  let socket = null;
  let reconnectTimer = null;

  function isVerified(market) {
    return Boolean(
      market?.is_premium
      && market?.published_prediction !== null
      && market?.published_prediction !== undefined
    );
  }

  function validDigit(value) {
    const number = Number(value);
    return Number.isInteger(number) && number >= 0 && number <= 9
      ? number
      : null;
  }

  function precisionCandidate(market) {
    const decision = market?.precision_decision || {};
    if (!decision?.verified_for_use) return null;
    return validDigit(decision?.candidate);
  }

  function statsFor(symbol) {
    if (!trialStats.has(symbol)) {
      trialStats.set(symbol, { wins: 0, losses: 0, resolved: 0 });
    }
    return trialStats.get(symbol);
  }

  function accuracyText(symbol) {
    const stats = statsFor(symbol);
    if (!stats.resolved) return "Precision trial: -- (n=0)";
    const accuracy = (stats.wins / stats.resolved) * 100;
    return `Precision trial: ${accuracy.toFixed(2)}% (n=${stats.resolved})`;
  }

  function cardFor(symbol) {
    if (typeof cards !== "undefined" && cards?.get) {
      const card = cards.get(symbol);
      if (card) return card;
    }
    return document.querySelector(`.market-card[data-symbol="${symbol}"]`);
  }

  function clearLegacyTimers(card) {
    if (!card) return;
    clearTimeout(card._scanRevealTimer);
    clearTimeout(card._scanRestartTimer);
    card._scanRevealTimer = null;
    card._scanRestartTimer = null;
  }

  function setScanner(card, { label, digit, status, note, revealed = true }) {
    if (!card) return;
    clearLegacyTimers(card);

    const digitNode = card.querySelector(".scanner-digit");
    const labelNode = card.querySelector(".scanner-label");
    const statusNode = card.querySelector(".match-status");
    const noteNode = card.querySelector(".scanner-note");

    card.classList.toggle("revealed", Boolean(revealed));

    if (digitNode) digitNode.textContent = digit;
    if (labelNode) labelNode.textContent = label;
    if (statusNode) statusNode.textContent = status;
    if (noteNode) noteNode.textContent = note;
  }

  function renderVerified(symbol, market) {
    const card = cardFor(symbol);
    setScanner(card, {
      label: "PREDICTION",
      digit: String(market.published_prediction),
      status: "Match Found",
      note: typeof evidenceNote === "function"
        ? evidenceNote(market, true)
        : "V12 precision evidence approved",
      revealed: true,
    });
  }

  function renderTrialPending(symbol, trial) {
    const card = cardFor(symbol);
    setScanner(card, {
      label: "PRECISION TEST",
      digit: String(trial.prediction),
      status: "Waiting for next Deriv tick",
      note: `Locked after tick ${trial.sourceEpoch} · ${accuracyText(symbol)}`,
      revealed: true,
    });
  }

  function renderTrialResult(symbol, trial) {
    const card = cardFor(symbol);
    const win = trial.result === "WIN";
    setScanner(card, {
      label: win ? "MATCH / WIN" : "MISS / LOSS",
      digit: String(trial.prediction),
      status: `Deriv Last Digit: ${trial.actual}`,
      note: `${trial.prediction} → ${trial.actual} · ${accuracyText(symbol)}`,
      revealed: true,
    });
  }

  function renderWaiting(symbol) {
    const card = cardFor(symbol);
    setScanner(card, {
      label: "SCANNING",
      digit: "--",
      status: "Waiting for validated edge",
      note: `V12 ignores raw model votes · ${accuracyText(symbol)}`,
      revealed: false,
    });
  }

  function formatTick(tick) {
    const quote = Number(tick?.quote);
    const pipSize = Number(tick?.pip_size);
    if (!Number.isFinite(quote) || !Number.isInteger(pipSize) || pipSize < 0) {
      return null;
    }
    const displayed = quote.toFixed(pipSize);
    const character = displayed[displayed.length - 1];
    if (!/\d/.test(character)) return null;
    return {
      epoch: Number(tick.epoch),
      displayed,
      digit: Number(character),
    };
  }

  function resolveThenCommit(symbol, tick) {
    const market = (typeof latestMarkets === "object" && latestMarkets)
      ? latestMarkets[symbol]
      : null;

    if (isVerified(market)) {
      trials.delete(symbol);
      renderVerified(symbol, market);
      return;
    }

    const existing = trials.get(symbol);

    if (existing?.state === "PENDING" && tick.epoch > existing.sourceEpoch) {
      const result = existing.prediction === tick.digit ? "WIN" : "LOSS";
      const stats = statsFor(symbol);
      stats.resolved += 1;
      if (result === "WIN") stats.wins += 1;
      else stats.losses += 1;

      const resolved = {
        ...existing,
        state: "RESOLVED",
        actual: tick.digit,
        resolvedEpoch: tick.epoch,
        resolvedQuote: tick.displayed,
        result,
      };
      trials.set(symbol, resolved);
      renderTrialResult(symbol, resolved);

      window.setTimeout(() => {
        const current = trials.get(symbol);
        if (current?.state === "RESOLVED" && current.resolvedEpoch === resolved.resolvedEpoch) {
          trials.delete(symbol);
          const newestMarket = (typeof latestMarkets === "object" && latestMarkets)
            ? latestMarkets[symbol]
            : null;
          if (!isVerified(newestMarket)) renderWaiting(symbol);
        }
      }, RESULT_HOLD_MS);
      return;
    }

    if (existing) {
      if (existing.state === "PENDING") renderTrialPending(symbol, existing);
      return;
    }

    const candidate = validDigit(trialCandidates.get(symbol));
    if (candidate === null) {
      renderWaiting(symbol);
      return;
    }

    const trial = {
      state: "PENDING",
      prediction: candidate,
      sourceEpoch: tick.epoch,
      sourceQuote: tick.displayed,
      createdAt: Date.now(),
    };
    trials.set(symbol, trial);
    renderTrialPending(symbol, trial);
  }

  function handleTick(rawTick) {
    const symbol = rawTick?.symbol;
    if (!symbol) return;

    const tick = formatTick(rawTick);
    if (!tick || !Number.isFinite(tick.epoch)) return;

    const previous = directTicks.get(symbol);
    if (previous && tick.epoch <= previous.epoch) return;
    directTicks.set(symbol, tick);

    resolveThenCommit(symbol, tick);
  }

  function subscribe(symbol) {
    if (!symbol || subscribed.has(symbol)) return;
    subscribed.add(symbol);

    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ ticks: symbol, subscribe: 1 }));
    }
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    socket = new WebSocket(WS_URL);

    socket.addEventListener("open", () => {
      subscribed.forEach((symbol) => {
        socket.send(JSON.stringify({ ticks: symbol, subscribe: 1 }));
      });
    });

    socket.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (_error) {
        return;
      }
      if (payload?.tick) handleTick(payload.tick);
    });

    socket.addEventListener("close", () => {
      socket = null;
      clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(connect, RECONNECT_MS);
    });

    socket.addEventListener("error", () => {
      try { socket.close(); } catch (_error) { /* no-op */ }
    });
  }

  function animateScannerSweeps(now) {
    const marketCards = document.querySelectorAll("#marketStack .market-card");
    const baseAngle = ((now % ROTATION_MS) / ROTATION_MS) * 360;

    marketCards.forEach((card, index) => {
      const sweep = card.querySelector(".scanner-sweep");
      if (!sweep) return;
      sweep.style.animation = "none";
      sweep.style.transform = `rotate(${baseAngle + index * 11}deg)`;
      sweep.style.opacity = card.classList.contains("revealed") ? "0.28" : "0.92";
    });

    window.requestAnimationFrame(animateScannerSweeps);
  }

  updateScanner = function updateScannerNextTickTrial(card, market, verified) {
    const symbol = card?.dataset?.symbol || market?.symbol;
    if (!symbol) return;

    clearLegacyTimers(card);
    subscribe(symbol);
    connect();

    if (verified || isVerified(market)) {
      trialCandidates.delete(symbol);
      trials.delete(symbol);
      renderVerified(symbol, market);
      return;
    }

    const candidate = precisionCandidate(market);
    if (candidate === null) trialCandidates.delete(symbol);
    else trialCandidates.set(symbol, candidate);

    const trial = trials.get(symbol);
    if (trial?.state === "PENDING") {
      renderTrialPending(symbol, trial);
      return;
    }
    if (trial?.state === "RESOLVED") {
      renderTrialResult(symbol, trial);
      return;
    }

    renderWaiting(symbol);
  };

  connect();
  window.requestAnimationFrame(animateScannerSweeps);
})();
