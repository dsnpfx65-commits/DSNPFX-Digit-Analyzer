from collections import defaultdict, deque


class MarketEngine:
    """
    DSNPFX Multi Market Memory Engine

    Keeps independent tick history
    for every Deriv synthetic market.
    """

    def __init__(self, max_history=200):
        self.max_history = max_history

        self.markets = defaultdict(
            lambda: deque(
                maxlen=self.max_history
            )
        )


    def add_tick(self, symbol, digit):
        self.markets[symbol].append(
            int(digit)
        )


    def history(self, symbol):
        return list(
            self.markets[symbol]
        )


    def samples(self, symbol):
        return len(
            self.markets[symbol]
        )


    def ready(self, symbol, minimum=20):
        return (
            len(self.markets[symbol])
            >= minimum
        )


    def statistics(self):

        return {
            symbol: {
                "samples": len(history),
                "latest": history[-1]
                if history else None
            }
            for symbol, history
            in self.markets.items()
        }
