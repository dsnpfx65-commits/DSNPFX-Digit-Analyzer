"""Shared live state for the DSNPFX volatility website."""

import asyncio
from copy import deepcopy

_state = {
    "status": "starting",
    "message": "Starting DSNPFX volatility intelligence...",
    "markets_monitoring": [],
    "market_count": 0,
}
_markets = {}
_opportunities = []
_statistics = {}
_subscribers = set()


def get_state():
    return deepcopy(_state)


def get_markets():
    return deepcopy(_markets)


def get_opportunities():
    return deepcopy(_opportunities)


def get_statistics():
    return deepcopy(_statistics)


async def publish_state(data, *, markets=None, opportunities=None, statistics=None):
    global _state, _markets, _opportunities, _statistics
    _state = deepcopy(data)
    if markets is not None:
        _markets = deepcopy(markets)
    if opportunities is not None:
        _opportunities = deepcopy(opportunities)
    if statistics is not None:
        _statistics = deepcopy(statistics)

    payload = {
        **deepcopy(_state),
        "markets": deepcopy(_markets),
        "opportunities": deepcopy(_opportunities),
        "statistics": deepcopy(_statistics),
    }
    for queue in list(_subscribers):
        try:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(deepcopy(payload))
        except Exception:
            _subscribers.discard(queue)


def subscribe():
    queue = asyncio.Queue(maxsize=1)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue):
    _subscribers.discard(queue)
