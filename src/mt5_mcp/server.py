"""
MCP server entrypoint.

Exposes the tool functions in `tools/` over the MCP stdio transport.

The server injects `STRATEGY_SYSTEM_PROMPT` from `strategy_config` into
server context and logs every tool call to `logs/server.log`.
"""

import sys
import logging
from functools import wraps
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


def _json_safe_tool(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return _json_safe(func(*args, **kwargs))

    return wrapped


def get_server_status() -> dict:
    """Return a non-trading health status without opening an MT5 session."""
    return {
        'status': 'ready',
        'server': 'mt5-trading',
        'transport': 'stdio',
        'trading_enabled': False,
    }


def get_system_prompt() -> dict:
    return {'system_prompt': STRATEGY_SYSTEM_PROMPT}


def main() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        logger.exception(
            "MCP SDK is required to run this server. "
            "Install the project dependencies from requirements.txt."
        )
        return 1

    server = FastMCP(
        "mt5-trading",
        instructions=STRATEGY_SYSTEM_PROMPT,
    )
    for name, func in TOOL_MAP.items():
        server.tool(name=name)(_json_safe_tool(func))
    server.tool(name='get_system_prompt')(get_system_prompt)
    server.tool(name='get_server_status')(get_server_status)

    logger.info("Starting MCP server over stdio")
    server.run(transport='stdio')
    return 0


if __name__ == '__main__':
    sys.exit(main())
