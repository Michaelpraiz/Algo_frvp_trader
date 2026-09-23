"""
MCP-style server entrypoint.

Attempts to use the `mcp` package if available. If not, falls back to a
minimal JSON-RPC-over-stdio dispatcher that exposes the tool functions in
`tools/`.

The server injects `STRATEGY_SYSTEM_PROMPT` from `strategy_config` into
server context and logs every tool call to `logs/server.log`.
"""

import sys
import json
import logging
from typing import Any
import numpy as np
import pandas as pd
from datetime import datetime, date

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - MCP_SERVER - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/server.log"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# Import tools
from .strategy_config import STRATEGY_NAME as STRATEGY_SYSTEM_PROMPT
from .tools import account_tools, market_tools, order_tools, analysis_tools, news_filter, frvp_tools

# Map method names to callables
TOOL_MAP = {
    # account
    'get_balance': account_tools.get_balance,
    'get_open_positions': account_tools.get_open_positions,
    'get_trade_history': account_tools.get_trade_history,
    'get_daily_pnl': account_tools.get_daily_pnl,
    # market
    'get_price': market_tools.get_price,
    'get_candles': market_tools.get_candles,
    'get_spread': market_tools.get_spread,
    'get_session_status': market_tools.get_session_status,
    # orders
    'place_market_order': order_tools.place_market_order,
    'place_limit_order': order_tools.place_limit_order,
    'modify_order': order_tools.modify_order,
    'close_position': order_tools.close_position,
    'close_all_positions': order_tools.close_all_positions,
    'move_to_breakeven': order_tools.move_to_breakeven,
    # analysis
    'analyze_symbol': analysis_tools.analyze_symbol,
    'get_market_structure': analysis_tools.get_market_structure,
    'get_order_blocks': analysis_tools.get_order_blocks,
    'get_fvg_zones': analysis_tools.get_fvg_zones,
    'get_liquidity_levels': analysis_tools.get_liquidity_levels,
    'check_trade_filters': analysis_tools.check_trade_filters,
    # FRVP
    'compute_fixed_range_volume_profile': frvp_tools.compute_fixed_range_volume_profile,
    'get_extended_frvp_levels': frvp_tools.get_extended_frvp_levels,
    # news
    'get_upcoming_news': news_filter.get_upcoming_news,
    'is_safe_to_trade': news_filter.is_safe_to_trade,
}


def _json_safe(value: Any):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (pd.Timestamp,)):
        return value.to_pydatetime().isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, 'to_dict'):
        return _json_safe(value.to_dict())
    return value


def handle_call(method: str, params: Any):
    func = TOOL_MAP.get(method)
    logger.info(f"Tool call: {method} params={params}")
    if method == 'get_system_prompt':
        return {'system_prompt': STRATEGY_SYSTEM_PROMPT}
    if method == 'get_server_status':
        return get_server_status()
    if method in {'initialize', 'notifications/initialized'}:
        return {'status': 'ok', 'server': 'mt5-trading'}
    if not func:
        return {'error': f'Method {method} not found'}
    try:
        if isinstance(params, dict):
            return func(**params)
        elif isinstance(params, list):
            return func(*params)
        elif params is None:
            return func()
        else:
            return func(params)
    except Exception as e:
        logger.exception(f"Error in tool {method}")
        return {'error': str(e)}


def get_server_status() -> dict:
    """Return a non-trading health status without opening an MT5 session."""
    return {
        'status': 'ready',
        'server': 'mt5-trading',
        'transport': 'stdio',
        'trading_enabled': False,
    }


def run_stdio_dispatcher():
    logger.info("Starting stdio JSON-RPC dispatcher (fallback)")
    # Simple loop: one JSON object per stdin line
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
            req_id = req.get('id')
            method = req.get('method')
            params = req.get('params')
            result = handle_call(method, params)
            resp = {'id': req_id, 'result': _json_safe(result)}
        except Exception as e:
            logger.exception("Error handling request")
            resp = {'id': None, 'error': str(e)}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


def main():
    # Try to use `mcp` package if present
    try:
        import mcp
        # Try to create an MCP server if the package exposes a simple API
        try:
            server = getattr(mcp, 'Server', None) or getattr(mcp, 'MCPServer', None)
            if server:
                s = server(tools=TOOL_MAP, system_prompt=STRATEGY_SYSTEM_PROMPT)
                logger.info("mcp server initialized")
                s.serve()
                return
        except Exception:
            logger.warning('mcp package present but failed to initialize server; falling back')
    except Exception:
        logger.info('mcp package not installed; using stdio dispatcher')

    run_stdio_dispatcher()


if __name__ == '__main__':
    main()
