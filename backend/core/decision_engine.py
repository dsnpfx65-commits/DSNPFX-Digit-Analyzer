class DecisionEngine:
    """
    DSNPFX Reliability-Weighted Decision Engine.

    Combines valid model predictions using adaptive weights.

    The argument order remains backward-compatible:
        frequency, markov, sequence, momentum
    """

    def __init__(
        self,
        frequency,
        markov,
        sequence,
        momentum=None,
        transition=None,
        weights=None,
    ):
        self.predictions = {
            "frequency": frequency,
            "markov": markov,
            "sequence": sequence,
            "transition": transition,
            "momentum": momentum,
        }

        voting_models = (
            "frequency",
            "markov",
            "sequence",
        )

        if weights is None:
            # Backward-compatible behavior for callers that
            # do not provide adaptive memory at all.
            working_weights = {
                "frequency": 33.333333,
                "markov": 33.333333,
                "sequence": 33.333334,
                "transition": 0.0,
                "momentum": 0.0,
            }
        else:
            # Explicit adaptive weights are authoritative.
            # In particular, 0.0 must remain 0.0.
            working_weights = {
                "frequency": 0.0,
                "markov": 0.0,
                "sequence": 0.0,
                "transition": 0.0,
                "momentum": 0.0,
            }

            for model in working_weights:
                try:
                    working_weights[model] = max(
                        0.0,
                        float(
                            weights.get(
                                model,
                                0.0,
                            )
                        ),
                    )
                except (TypeError, ValueError):
                    working_weights[model] = 0.0

        # Transition remains research metadata because it
        # duplicates the first-order Markov vote.
        working_weights["transition"] = 0.0
        working_weights["momentum"] = 0.0

        voting_total = sum(
            working_weights[model]
            for model in voting_models
        )

        if voting_total > 0.0:
            for model in voting_models:
                working_weights[model] = (
                    working_weights[model]
                    / voting_total
                    * 100.0
                )
        else:
            # Critical V8.2 behavior:
            # no earned evidence stays no earned evidence.
            for model in voting_models:
                working_weights[model] = 0.0

        self.weights = working_weights

    def analyze(self):
        weighted_scores = {
            digit: 0.0
            for digit in range(10)
        }

        active_weight = 0.0
        active_models = 0

        for model, prediction in self.predictions.items():
            if prediction is None:
                continue

            try:
                prediction = int(prediction)
            except (TypeError, ValueError):
                continue

            if not 0 <= prediction <= 9:
                continue

            weight = float(
                self.weights.get(model, 0.0)
            )

            if weight <= 0:
                continue

            weighted_scores[prediction] += weight
            active_weight += weight
            active_models += 1

        if active_weight == 0:
            return {
                "prediction": None,
                "confidence": 0,
                "vote_confidence": 0,
                "strength": "LOW",
                "decision": "WAIT",
                "market_condition": "INSUFFICIENT_DATA",
                "agreement_scores": weighted_scores,
                "confidence_margin": 0,
                "active_models": 0,
            }

        normalised_scores = {
            digit: round(
                score / active_weight * 100,
                2,
            )
            for digit, score
            in weighted_scores.items()
        }

        ranked_digits = sorted(
            normalised_scores.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )

        prediction = ranked_digits[0][0]
        vote_confidence = ranked_digits[0][1]
        second_score = ranked_digits[1][1]

        confidence_margin = round(
            vote_confidence - second_score,
            2,
        )

        top_digits = [
            digit
            for digit, score in ranked_digits
            if score == vote_confidence
            and score > 0
        ]

        unresolved_tie = len(top_digits) > 1

        if unresolved_tie:
            prediction = None

        # Three active models are sufficient for full
        # participation confidence. A fourth model adds a vote
        # but does not artificially raise participation above 1.
        participation_factor = min(
            active_models / 3,
            1.0,
        )

        confidence = round(
            vote_confidence * participation_factor,
            2,
        )

        if confidence >= 75:
            strength = "PREMIUM"
        elif confidence >= 60:
            strength = "HIGH"
        elif confidence >= 45:
            strength = "MEDIUM"
        else:
            strength = "LOW"

        if (
            not unresolved_tie
            and confidence >= 70
            and confidence_margin >= 20
            and active_models >= 2
        ):
            decision = "SIGNAL"
        else:
            decision = "WAIT"

        if confidence >= 70:
            market_condition = "STRONG_AGREEMENT"
        elif confidence >= 50:
            market_condition = "MIXED"
        else:
            market_condition = "WEAK_AGREEMENT"

        return {
            "prediction": prediction,
            "confidence": confidence,
            "vote_confidence": vote_confidence,
            "strength": strength,
            "decision": decision,
            "market_condition": market_condition,
            "agreement_scores": normalised_scores,
            "confidence_margin": confidence_margin,
            "active_models": active_models,
            "unresolved_tie": unresolved_tie,
            "tied_digits": top_digits,
        }
