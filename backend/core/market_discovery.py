import asyncio
import json
import websockets


DERIV_WS = (
    "wss://api.derivws.com/"
    "trading/v1/options/ws/public"
)


class MarketDiscovery:

    def __init__(self):
        self.markets = []


    async def fetch(self):

        async with websockets.connect(
            DERIV_WS,
            ping_interval=30,
            ping_timeout=30,
        ) as ws:

            await ws.send(
                json.dumps({
                    "active_symbols": "full"
                })
            )

            response = await ws.recv()

            data = json.loads(response)

            symbols = data.get(
                "active_symbols",
                []
            )

            for item in symbols:

                name = item.get(
                    "underlying_symbol_name",
                    ""
                )

                symbol = item.get(
                    "underlying_symbol",
                    ""
                )


                if any(
                    key in name.lower()
                    for key in [
                        "volatility",
                        "step",
                        "jump",
                        "boom",
                        "crash",
                    ]
                ):

                    self.markets.append(
                        {
                            "symbol": symbol,
                            "name": name,
                            "type": self.classify(name),
                        }
                    )

        return self.markets


    def classify(self, name):

        name = name.lower()

        if "volatility" in name:
            return "VOLATILITY"

        if "step" in name:
            return "STEP"

        if "jump" in name:
            return "JUMP"

        if "boom" in name:
            return "BOOM"

        if "crash" in name:
            return "CRASH"

        return "UNKNOWN"



async def main():

    print(
        "\n===== DSNPFX MARKET DISCOVERY ====="
    )

    engine = MarketDiscovery()

    markets = await engine.fetch()


    print(
        f"Found {len(markets)} markets\n"
    )


    for market in markets:

        print(
            f"{market['type']:12} | "
            f"{market['symbol']:10} | "
            f"{market['name']}"
        )



if __name__ == "__main__":

    asyncio.run(main())
