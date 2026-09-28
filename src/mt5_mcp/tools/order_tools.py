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
from ..config import ACCOUNT_TYPE
from ..risk_manager import get_risk_manager
from ..strategy_config import FILTERS, RISK_MANAGEMENT
import math

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

MAX_SINGLE_TRADE_LOTS = float(RISK_MANAGEMENT["max_single_trade_lots"])


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
    minimum = float(RISK_MANAGEMENT["min_single_trade_lots"])
    if not math.isfinite(requested) or requested < minimum or requested > MAX_SINGLE_TRADE_LOTS:
        message = (
            f"volume {requested} must be between "
            f"{RISK_MANAGEMENT['min_single_trade_lots']} and {MAX_SINGLE_TRADE_LOTS} lots"
        )
        _audit("REJECTED", action=action, reason=message, volume=requested)
        return {"success": False, "error": message}
    return None


def _validate_broker_order(
    action: str, symbol: str, side: str, volume: float, entry_price: float,
    sl: Optional[float], tp: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Enforce broker volume, stop, daily loss, margin, and 3% risk limits."""
    normalized_side = side.lower()
    if normalized_side not in {"buy", "sell"}:
        return {"success": False, "error": "side must be 'buy' or 'sell'"}
    if sl is None or sl <= 0:
        return {"success": False, "error": "A protective stop loss is required"}
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"success": False, "error": f"Symbol {symbol} not found"}
    point = float(info.point)
    tick_size = float(getattr(info, "trade_tick_size", 0) or point)
    step = float(info.volume_step)
    minimum = max(float(info.volume_min), float(RISK_MANAGEMENT["min_single_trade_lots"]))
    maximum = min(float(info.volume_max), MAX_SINGLE_TRADE_LOTS)
    if volume < minimum or volume > maximum:
        return {"success": False, "error": f"volume must be between {minimum} and {maximum} lots for {symbol}"}
    if not math.isfinite(volume) or step <= 0 or abs((volume - minimum) / step - round((volume - minimum) / step)) > 1e-7:
        return {"success": False, "error": f"volume must align to broker step {step:g}"}

    is_buy = normalized_side == "buy"
    if (is_buy and sl >= entry_price) or (not is_buy and sl <= entry_price):
        return {"success": False, "error": "stop loss must be on the loss side of the entry price"}
    if tp is not None and tp > 0 and (
        (is_buy and tp <= entry_price) or (not is_buy and tp >= entry_price)
    ):
        return {"success": False, "error": "take profit must be on the profit side of the entry price"}
    min_distance = max(float(info.trade_stops_level) * point, tick_size)
    if abs(entry_price - sl) + 1e-12 < min_distance:
        return {"success": False, "error": f"stop loss is inside broker minimum distance {min_distance:g}"}
    if tp is not None and tp > 0 and abs(entry_price - tp) + 1e-12 < min_distance:
        return {"success": False, "error": f"take profit is inside broker minimum distance {min_distance:g}"}

    tick = mt5.symbol_info_tick(symbol)
    max_spread = FILTERS.get("maximum_spread_points", {}).get(symbol)
    if tick is None:
        return {"success": False, "error": f"Cannot retrieve current quote for {symbol}"}
    spread_points = (float(tick.ask) - float(tick.bid)) / point
    if max_spread is not None and spread_points > float(max_spread):
        return {"success": False, "error": f"spread {spread_points:.1f} points exceeds limit {max_spread}"}

    account = mt5.account_info()
    if account is None or float(account.balance) <= 0:
        return {"success": False, "error": "Cannot retrieve valid account balance"}
    daily = get_risk_manager().check_daily_drawdown()
    if not daily.get("can_trade", False):
        return {"success": False, "error": daily.get("message", "Daily risk limit blocks trading")}

    trade_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    adverse_sl = float(sl) - float(FILTERS["maximum_slippage_points"]) * point if is_buy else (
        float(sl) + float(FILTERS["maximum_slippage_points"]) * point
    )
    loss = mt5.order_calc_profit(trade_type, symbol, volume, entry_price, adverse_sl)
    if loss is None:
        return {"success": False, "error": f"Broker loss calculation failed: {mt5.last_error()}"}
    commission_per_side = float(
        FILTERS.get("commission_per_lot_per_side", {}).get(symbol, 0.0)
    )
    projected_loss = abs(float(loss)) + 2 * commission_per_side * volume
    risk_cap = float(account.balance) * float(RISK_MANAGEMENT["max_single_trade_risk_percent"]) / 100
    if projected_loss > risk_cap + 0.01:
        return {
            "success": False,
            "error": f"projected loss ${projected_loss:.2f} exceeds 3% risk cap ${risk_cap:.2f}",
        }

    margin = mt5.order_calc_margin(trade_type, symbol, volume, entry_price)
    if margin is None:
        return {"success": False, "error": f"Broker margin calculation failed: {mt5.last_error()}"}
    if float(margin) > float(account.margin_free):
        return {"success": False, "error": "required margin exceeds available free margin"}
    positions = mt5.positions_get()
    if positions is None:
        return {"success": False, "error": f"Could not check existing positions: {mt5.last_error()}"}
    if len(positions) >= int(RISK_MANAGEMENT["max_open_trades"]):
        return {"success": False, "error": "maximum concurrent position count reached"}

    open_risk = 0.0
    for position in positions:
        position_sl = float(position.sl)
        if position_sl <= 0:
            return {"success": False, "error": "an existing position has no stop; aggregate risk cannot be verified"}
        position_type = mt5.ORDER_TYPE_BUY if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_SELL
        position_loss = mt5.order_calc_profit(
            position_type, position.symbol, float(position.volume),
            float(position.price_open), position_sl,
        )
        if position_loss is None:
            return {"success": False, "error": "could not calculate existing open-position risk"}
        open_risk += abs(float(position_loss))
    aggregate_cap = (
        float(account.balance) * float(RISK_MANAGEMENT["total_risk_per_max_open_trades"]) / 100
    )
    if open_risk + projected_loss > aggregate_cap + 0.01:
        return {"success": False, "error": "combined open-position risk would exceed the 6% account cap"}
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
        if side.lower() not in {"buy", "sell"}:
            return {"success": False, "error": "side must be 'buy' or 'sell'"}
        _audit("REQUESTED", action="place_market_order", symbol=symbol, side=side, volume=volume, account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            _audit("FAILED", action="place_market_order", symbol=symbol, reason="MT5 client not initialized")
            return {"success": False, "error": "MT5 client not initialized"}

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            _audit("FAILED", action="place_market_order", symbol=symbol, reason="symbol not found")
            return {"success": False, "error": f"Symbol {symbol} not found"}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": f"Cannot retrieve current quote for {symbol}"}
        price = tick.ask if side.lower() == 'buy' else tick.bid
        blocked = _validate_broker_order(
            "place_market_order", symbol, side, volume, float(price), sl, tp
        )
        if blocked:
            _audit("REJECTED", action="place_market_order", symbol=symbol, reason=blocked["error"])
            return blocked
        order_type = mt5.ORDER_TYPE_BUY if side.lower() == 'buy' else mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "deviation": int(FILTERS["maximum_slippage_points"]),
            "magic": 234000,
            "comment": comment,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        checked = mt5.order_check(request)
        if checked is None or checked.retcode not in {0, mt5.TRADE_RETCODE_DONE}:
            error = f"Broker rejected order pre-check: {checked}"
            _audit("REJECTED", action="place_market_order", symbol=symbol, reason=error)
            return {"success": False, "error": error}
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
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
        if side.lower() not in {"buy", "sell"}:
            return {"success": False, "error": "side must be 'buy' or 'sell'"}
        _audit("REQUESTED", action="place_limit_order", symbol=symbol, side=side, volume=volume, account_type=ACCOUNT_TYPE)
        if not _ensure_initialized():
            return {"success": False, "error": "MT5 client not initialized"}

        blocked = _validate_broker_order(
            "place_limit_order", symbol, side, volume, float(price), sl, tp
        )
        if blocked:
            _audit("REJECTED", action="place_limit_order", symbol=symbol, reason=blocked["error"])
            return blocked
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if side.lower() == 'buy' else mt5.ORDER_TYPE_SELL_LIMIT
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "deviation": int(FILTERS["maximum_slippage_points"]),
            "magic": 234000,
            "comment": comment,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        checked = mt5.order_check(request)
        if checked is None or checked.retcode not in {0, mt5.TRADE_RETCODE_DONE}:
            error = f"Broker rejected pending order pre-check: {checked}"
            _audit("REJECTED", action="place_limit_order", symbol=symbol, reason=error)
            return {"success": False, "error": error}
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
