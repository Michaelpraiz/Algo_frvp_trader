"""
Market data tools for MCP.

Functions:
- get_price(symbol)
- get_candles(symbol, timeframe, count)
- get_spread(symbol)
- get_session_status()

These wrap `mt5_client` and `strategy_config` session definitions.
"""

from typing import Optional, Dict, Any
from datetime import datetime, time
import logging

from ..mt5_client import get_client
from ..strategy_config import SESSIONS

logger = logging.getLogger(__name__)


def get_price(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        client = get_client()
        tick = client.get_tick(symbol)
        return tick
    except Exception as e:
        logger.exception("get_price error")
        return None


def get_candles(symbol: str, timeframe: str, count: int = 100):
    try:
        client = get_client()
        df = client.get_candles(symbol, timeframe, count)
        # return DataFrame as dict for JSON-serializable transport
        if df is None:
            return None
        return df.to_dict(orient='records')
    except Exception as e:
        logger.exception("get_candles error")
        return None


def get_spread(symbol: str) -> Optional[float]:
    """Return spread in pips (points) using symbol info or tick."""
    try:
        client = get_client()
        tick = client.get_tick(symbol)
        if not tick:
            return None
        # spread in pips (points). Prefer spread_points if provided by MT5 client.
        spread_points = tick.get('spread_points')
        if spread_points is not None:
            return float(spread_points)
        ask = tick.get('ask', 0.0)
        bid = tick.get('bid', 0.0)
        # fallback: assume 4-5 digit forex -> convert to pips
        return round((ask - bid) * 10000, 1)
    except Exception as e:
        logger.exception("get_spread error")
        return None


def _time_from_hhmm(hhmm: str) -> time:
    h, m = map(int, hhmm.split(':'))
    return time(hour=h, minute=m)


def get_session_status(timezone: str = 'utc') -> Dict[str, Any]:
    """Return which trading session is currently active (based on UTC times in config).

    timezone: 'utc' (default) or 'wat' supported based on `SESSIONS` keys.
    """
    now = datetime.utcnow().time()
    active = []
    for name, cfg in SESSIONS.items():
        if not isinstance(cfg, dict):
            continue
        open_key = 'open_utc' if timezone == 'utc' else 'open_wat'
        close_key = 'close_utc' if timezone == 'utc' else 'close_wat'
        if open_key in cfg and close_key in cfg:
            start = _time_from_hhmm(cfg[open_key])
            end = _time_from_hhmm(cfg[close_key])
            if start <= now <= end:
                active.append(name)
    return {'active_sessions': active, 'time_utc': datetime.utcnow().isoformat()}
