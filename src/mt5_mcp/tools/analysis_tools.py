"""
Analysis wrappers that expose the TradeEngine capabilities to MCP.

Functions:
- analyze_symbol(symbol)
- get_market_structure(symbol, timeframe)
- get_order_blocks(symbol)
- get_fvg_zones(symbol)
- get_liquidity_levels(symbol)
- check_trade_filters(symbol)

These call into `trade_engine.get_trade_engine()` and return JSON-serializable dicts.
"""

from typing import Dict, Any, List
import logging
import dataclasses

from ..trade_engine import get_trade_engine, OrderBlock, FairValueGap

logger = logging.getLogger(__name__)


def _serialize(obj):
    if dataclasses.is_dataclass(obj):
        d = dataclasses.asdict(obj)
        # convert datetimes to isoformat
        for k, v in d.items():
            if hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
        return d
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    return obj


def analyze_symbol(symbol: str) -> Dict[str, Any]:
    engine = get_trade_engine()
    plan = engine.generate_trade_plan(symbol)
    # serialize nested dataclasses
    if 'analysis' in plan:
        for k, v in plan['analysis'].items():
            if isinstance(v, list):
                plan['analysis'][k] = _serialize(v)
            elif dataclasses.is_dataclass(v):
                plan['analysis'][k] = _serialize(v)
    return plan


def get_market_structure(symbol: str, timeframe: str = 'H1') -> Dict[str, Any]:
    engine = get_trade_engine()
    return engine.detect_bos_choch(symbol, timeframe)


def get_order_blocks(symbol: str, timeframe: str = 'H1') -> Dict[str, Any]:
    engine = get_trade_engine()
    res = engine.find_order_blocks(symbol, timeframe)
    # serialize order_blocks
    res['order_blocks'] = _serialize(res.get('order_blocks', []))
    return res


def get_fvg_zones(symbol: str, timeframe: str = 'H1') -> Dict[str, Any]:
    engine = get_trade_engine()
    res = engine.find_fvg(symbol, timeframe)
    res['fvgs'] = _serialize(res.get('fvgs', []))
    return res


def get_liquidity_levels(symbol: str, timeframe: str = 'H1') -> Dict[str, Any]:
    engine = get_trade_engine()
    return engine.find_liquidity_levels(symbol, timeframe)


def check_trade_filters(symbol: str) -> Dict[str, Any]:
    engine = get_trade_engine()
    # Example filters: spread, session trade allowed, max open trades
    from market_tools import get_spread, get_session_status
    from tools.account_tools import get_open_positions

    reasons = []
    ok = True

    spread = get_spread(symbol)
    if spread is not None and spread > 10:  # arbitrary guard: 10 pips
        ok = False
        reasons.append(f"spread_too_wide: {spread}")

    sessions = get_session_status()
    if sessions and not sessions.get('active_sessions'):
        ok = False
        reasons.append("no_active_session")

    open_positions = get_open_positions() or []
    if len(open_positions) >= 5:
        ok = False
        reasons.append("max_open_trades_reached")

    return {"symbol": symbol, "safe": ok, "reasons": reasons}
