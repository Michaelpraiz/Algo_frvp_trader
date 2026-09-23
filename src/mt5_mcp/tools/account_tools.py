"""
Account tools exposed to MCP.

Functions:
- get_balance()
- get_open_positions()
- get_trade_history(start_iso, end_iso)
- get_daily_pnl()

These are thin, safe wrappers around `mt5_client`.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

from ..mt5_client import get_client

logger = logging.getLogger(__name__)


def get_balance() -> Optional[Dict[str, Any]]:
    """Return current balance, equity, margin info."""
    try:
        client = get_client()
        info = client.get_account_info()
        return info
    except Exception as e:
        logger.exception("get_balance error")
        return None


def get_open_positions() -> Optional[List[Dict[str, Any]]]:
    """Return all live positions with PnL."""
    try:
        client = get_client()
        positions = client.get_open_positions()
        return positions or []
    except Exception as e:
        logger.exception("get_open_positions error")
        return None


def get_trade_history(start_iso: str, end_iso: str) -> Optional[List[Dict[str, Any]]]:
    """Return closed trades between ISO datetimes (inclusive).

    Accepts ISO date strings (YYYY-MM-DD or full ISO). Falls back to last 30 days if parsing fails.
    """
    try:
        client = get_client()

        # parse dates
        try:
            start = datetime.fromisoformat(start_iso)
        except Exception:
            start = datetime.now(timezone.utc) - timedelta(days=30)
        try:
            end = datetime.fromisoformat(end_iso)
        except Exception:
            end = datetime.now(timezone.utc)

        # Determine days window (simple approach)
        delta_days = max(1, (end - start).days + 1)
        history = client.get_order_history(days=delta_days) or []

        # filter
        filtered = [h for h in history if start <= h.get('time', start) <= end]
        return filtered
    except Exception as e:
        logger.exception("get_trade_history error")
        return None


def get_daily_pnl() -> Optional[Dict[str, float]]:
    """Return today's realized + unrealized PnL.

    realized: sum of closed deals today
    unrealized: sum of open positions' profit
    total: realized + unrealized
    """
    try:
        client = get_client()
        open_pos = client.get_open_positions() or []
        unrealized = sum([p.get('profit', 0.0) for p in open_pos])

        # closed deals today
        today = datetime.now(timezone.utc).date()
        closed = client.get_order_history(days=1) or []
        realized = 0.0
        for d in closed:
            t = d.get('time')
            if t and getattr(t, 'date', lambda: None)() == today:
                realized += d.get('profit', 0.0)

        return {"realized": realized, "unrealized": unrealized, "total": realized + unrealized}
    except Exception as e:
        logger.exception("get_daily_pnl error")
        return None
