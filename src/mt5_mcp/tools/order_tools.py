"""
Order execution tools for MCP.

Functions:
- place_market_order(symbol, side, volume, sl=None, tp=None)
- place_limit_order(symbol, side, volume, price, sl=None, tp=None)
- modify_order(ticket, sl=None, tp=None)
- close_position(ticket, volume=None)
- close_all_positions()
- move_to_breakeven(ticket)

These are thin wrappers around the MetaTrader5 API.
"""

from typing import Optional, Dict, Any
import os
import logging

import MetaTrader5 as mt5
from ..mt5_client import get_client
from ..config import ACCOUNT_TYPE, get_setting

logger = logging.getLogger(__name__)

ORDER_ACTION_LOG = "logs/order_actions.log"
os.makedirs(os.path.dirname(ORDER_ACTION_LOG), exist_ok=True)
_audit_logger = logging.getLogger("order_actions")
if not _audit_logger.handlers:
    _audit_handler = logging.FileHandler(ORDER_ACTION_LOG)
    _audit_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    _audit_logger.addHandler(_audit_handler)
    _audit_logger.setLevel(logging.INFO)
    _audit_logger.propagate = False

MAX_SINGLE_TRADE_LOTS = float(get_setting("MAX_SINGLE_TRADE_LOTS", "0.01"))


def _audit(event: str, **details) -> None:
    _audit_logger.info("%s %s", event, details)


def _require_confirmation(action: str, confirm: bool) -> Optional[Dict[str, Any]]:
    if confirm is not True:
        message = f"{action} requires explicit confirm=true"
        _audit("REJECTED", action=action, reason=message)
        return {"success": False, "error": message}
    if ACCOUNT_TYPE not in {"demo", "live"}:
        message = f"Invalid ACCOUNT_TYPE={ACCOUNT_TYPE!r}; expected demo or live"
        _audit("REJECTED", action=action, reason=message)
        return {"success": False, "error": message}
    return None


def _validate_volume(action: str, volume: float) -> Optional[Dict[str, Any]]:
    try:
        requested = float(volume)
    except (TypeError, ValueError):
        message = "volume must be numeric"
        _audit("REJECTED", action=action, reason=message, volume=volume)
        return {"success": False, "error": message}
    if requested <= 0 or requested > MAX_SINGLE_TRADE_LOTS:
        message = f"volume {requested} exceeds max single trade size {MAX_SINGLE_TRADE_LOTS}"
        _audit("REJECTED", action=action, reason=message, volume=requested)
        return {"success": False, "error": message}
    return None


def _ensure_initialized():
    try:
        client = get_client()
        return True
    except Exception:
        return False


def place_market_order(symbol: str, side: str, volume: float, sl: Optional[float] = None, tp: Optional[float] = None, comment: str = "", confirm: bool = False) -> Dict[str, Any]:
    """Place a market order. side: 'buy' or 'sell'"""
    try:
        blocked = _require_confirmation("place_market_order", confirm) or _validate_volume("place_market_order", volume)
        if blocked:
            return blocked
        _audit("REQUESTED", action="place_market_order", symbol=symbol, side=side, volume=volume, account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            _audit("FAILED", action="place_market_order", symbol=symbol, reason="MT5 client not initialized")
            return {"success": False, "error": "MT5 client not initialized"}

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            _audit("FAILED", action="place_market_order", symbol=symbol, reason="symbol not found")
            return {"success": False, "error": f"Symbol {symbol} not found"}

        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if side.lower() == 'buy' else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if side.lower() == 'buy' else mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "deviation": 20,
            "magic": 234000,
            "comment": comment,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == 10009 or (hasattr(result, 'retcode') and result.retcode == mt5.TRADE_RETCODE_DONE):
            _audit("EXECUTED", action="place_market_order", symbol=symbol, volume=volume, result=str(result))
            return {"success": True, "order": result._asdict() if hasattr(result, '_asdict') else str(result)}
        _audit("FAILED", action="place_market_order", symbol=symbol, result=str(result))
        return {"success": False, "result": str(result)}

    except Exception as e:
        _audit("ERROR", action="place_market_order", symbol=symbol, error=str(e))
        logger.exception("place_market_order error")
        return {"success": False, "error": str(e)}


def place_limit_order(symbol: str, side: str, volume: float, price: float, sl: Optional[float] = None, tp: Optional[float] = None, comment: str = "", confirm: bool = False) -> Dict[str, Any]:
    try:
        blocked = _require_confirmation("place_limit_order", confirm) or _validate_volume("place_limit_order", volume)
        if blocked:
            return blocked
        _audit("REQUESTED", action="place_limit_order", symbol=symbol, side=side, volume=volume, account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            return {"success": False, "error": "MT5 client not initialized"}

        order_type = mt5.ORDER_TYPE_BUY_LIMIT if side.lower() == 'buy' else mt5.ORDER_TYPE_SELL_LIMIT
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "deviation": 20,
            "magic": 234000,
            "comment": comment,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        result = mt5.order_send(request)
        success = bool(result and result.retcode in {10008, 10009})
        _audit("EXECUTED" if success else "FAILED", action="place_limit_order", symbol=symbol, result=str(result))
        return {"success": success, "result": str(result)}
    except Exception as e:
        _audit("ERROR", action="place_limit_order", symbol=symbol, error=str(e))
        logger.exception("place_limit_order error")
        return {"success": False, "error": str(e)}


def modify_order(ticket: int, sl: Optional[float] = None, tp: Optional[float] = None, confirm: bool = False) -> Dict[str, Any]:
    try:
        blocked = _require_confirmation("modify_order", confirm)
        if blocked:
            return blocked
        _audit("REQUESTED", action="modify_order", ticket=ticket, account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            return {"success": False, "error": "MT5 client not initialized"}
        # Try modifying pending order first
        res = mt5.order_modify(ticket, 0.0, sl if sl else 0.0, tp if tp else 0.0, 0)
        _audit("EXECUTED", action="modify_order", ticket=ticket, result=str(res))
        return {"success": True, "result": str(res)}
    except Exception as e:
        _audit("ERROR", action="modify_order", ticket=ticket, error=str(e))
        logger.exception("modify_order error")
        return {"success": False, "error": str(e)}


def close_position(ticket: int, volume: Optional[float] = None, confirm: bool = False) -> Dict[str, Any]:
    try:
        blocked = _require_confirmation("close_position", confirm)
        if blocked:
            return blocked
        _audit("REQUESTED", action="close_position", ticket=ticket, volume=volume, account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            return {"success": False, "error": "MT5 client not initialized"}
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": "Position not found"}
        pos = positions[0]
        symbol = pos.symbol
        vol = volume if volume else pos.volume
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(vol),
            "type": close_type,
            "position": pos.ticket,
            "price": float(price),
            "deviation": 20,
            "magic": 234000,
            "comment": "close",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        success = bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)
        _audit("EXECUTED" if success else "FAILED", action="close_position", ticket=ticket, result=str(result))
        return {"success": success, "result": str(result)}
    except Exception as e:
        _audit("ERROR", action="close_position", ticket=ticket, error=str(e))
        logger.exception("close_position error")
        return {"success": False, "error": str(e)}


def close_all_positions() -> Dict[str, Any]:
    try:
        _audit("KILL_SWITCH_REQUESTED", action="close_all_positions", account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            return {"success": False, "error": "MT5 client not initialized"}
        positions = mt5.positions_get()
        results = []
        for p in positions:
            results.append(close_position(p.ticket, confirm=True))
        success = all(result.get("success", False) for result in results) if results else True
        _audit("KILL_SWITCH_COMPLETED", action="close_all_positions", success=success, count=len(results))
        return {"success": success, "results": results}
    except Exception as e:
        _audit("KILL_SWITCH_ERROR", action="close_all_positions", error=str(e))
        logger.exception("close_all_positions error")
        return {"success": False, "error": str(e)}


def move_to_breakeven(ticket: int, confirm: bool = False) -> Dict[str, Any]:
    try:
        blocked = _require_confirmation("move_to_breakeven", confirm)
        if blocked:
            return blocked
        _audit("REQUESTED", action="move_to_breakeven", ticket=ticket, account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            return {"success": False, "error": "MT5 client not initialized"}
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": "Position not found"}
        pos = positions[0]
        entry = pos.price_open
        # set SL to entry
        return modify_order(ticket, sl=entry, tp=pos.tp, confirm=True)
    except Exception as e:
        _audit("ERROR", action="move_to_breakeven", ticket=ticket, error=str(e))
        logger.exception("move_to_breakeven error")
        return {"success": False, "error": str(e)}
