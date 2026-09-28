"""Causal OHLC backtesting and walk-forward parameter search."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from collections import Counter
import itertools
import json
import logging
from numbers import Real
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .strategy_config import FILTERS, RISK_MANAGEMENT

logger = logging.getLogger(__name__)
SUPPORTED_TIMEFRAMES = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}
_TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}


@dataclass(frozen=True)
class BacktestParameters:
    """Backtestable numeric thresholds; never written to live strategy config."""

    minimum_rr: float = float(FILTERS["min_rr_to_take_trade"])
    maximum_rr: float = float(FILTERS["max_rr_to_take_trade"])
    risk_percent: float = float(RISK_MANAGEMENT["max_single_trade_risk_percent"])
    session_start_hour: int = 7
    session_end_hour: int = 21
    frvp_lookback_period: int = 100
    sl_buffer_points: float = 2.0
    swing_lookback: int = 5
    value_area_pct: float = 0.70
    tick_size: float = 0.0
    fallback_spread_points: float = 24.0
    slippage_points_per_fill: float = 1.0
    commission_per_lot_per_side: float = 0.0
    minimum_volume: float = 0.01
    maximum_volume: float = 10.0
    volume_step: float = 0.01
    broker_stops_level_points: float = 0.0
    leverage: float = 1000.0
    contract_size: float = 100.0
    tick_value_per_lot: float = 1.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> "BacktestParameters":
        allowed = cls.__dataclass_fields__
        unknown = set(values or {}) - set(allowed)
        if unknown:
            raise ValueError(f"Unknown backtest parameter(s): {', '.join(sorted(unknown))}")
        result = cls(**dict(values or {}))
        for name in (
            "minimum_rr", "maximum_rr", "risk_percent", "sl_buffer_points",
            "value_area_pct", "tick_size", "fallback_spread_points",
            "slippage_points_per_fill", "commission_per_lot_per_side",
            "minimum_volume", "maximum_volume", "volume_step",
            "broker_stops_level_points", "leverage", "contract_size", "tick_value_per_lot",
        ):
            value = getattr(result, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if not 1 <= result.minimum_rr <= 10 or not 1 <= result.maximum_rr <= 10:
            raise ValueError("R:R bounds must be between 1:1 and 1:10")
        if result.minimum_rr > result.maximum_rr:
            raise ValueError("minimum_rr cannot exceed maximum_rr")
        if not 0 < result.risk_percent <= float(RISK_MANAGEMENT["max_single_trade_risk_percent"]):
            raise ValueError("risk_percent must be positive and cannot exceed the 3% per-trade cap")
        if any(isinstance(hour, bool) or not isinstance(hour, int)
               for hour in (result.session_start_hour, result.session_end_hour)):
            raise ValueError("session hours must be integers from 0 through 23")
        if not (0 <= result.session_start_hour <= 23 and 0 <= result.session_end_hour <= 23):
            raise ValueError("session hours must be integers from 0 through 23")
        if result.session_start_hour == result.session_end_hour:
            raise ValueError("session start and end hours cannot be equal")
        if isinstance(result.frvp_lookback_period, bool) or not isinstance(result.frvp_lookback_period, int):
            raise ValueError("frvp_lookback_period must be an integer")
        if result.frvp_lookback_period < 10:
            raise ValueError("frvp_lookback_period must be at least 10 bars")
        if result.sl_buffer_points < 0:
            raise ValueError("sl_buffer_points cannot be negative")
        if isinstance(result.swing_lookback, bool) or not isinstance(result.swing_lookback, int):
            raise ValueError("swing_lookback must be an integer")
        if result.swing_lookback < 2:
            raise ValueError("swing_lookback must be at least 2")
        if not 0 < result.value_area_pct <= 1:
            raise ValueError("value_area_pct must be greater than 0 and at most 1")
        if result.tick_size < 0:
            raise ValueError("tick_size cannot be negative")
        if (result.fallback_spread_points < 0 or result.slippage_points_per_fill < 0
                or result.commission_per_lot_per_side < 0 or result.broker_stops_level_points < 0):
            raise ValueError("execution costs and broker stop distances cannot be negative")
        if (result.minimum_volume <= 0 or result.maximum_volume < result.minimum_volume
                or result.volume_step <= 0 or result.leverage <= 0
                or result.contract_size <= 0 or result.tick_value_per_lot <= 0):
            raise ValueError("broker volume, leverage, and contract specifications must be positive")
        return result


def normalize_candles(candles: pd.DataFrame) -> pd.DataFrame:
    """Validate, sort, and normalize supported OHLCV input to UTC."""
    metadata = dict(candles.attrs)
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"Candle data is missing required columns: {', '.join(sorted(missing))}")
    result = candles.copy()
    if "tick_volume" in result.columns and "volume" not in result.columns:
        result.rename(columns={"tick_volume": "volume"}, inplace=True)
    if "volume" not in result.columns:
        result["volume"] = 1.0
    if "spread" in result.columns and "spread_points" not in result.columns:
        result.rename(columns={"spread": "spread_points"}, inplace=True)
    if "spread_points" not in result.columns:
        result["spread_points"] = np.nan
    result["time"] = pd.to_datetime(result["time"], utc=True, errors="coerce")
    if result["time"].isna().any():
        raise ValueError("Candle time values must be valid timestamps")
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ValueError("OHLCV values must be finite numbers")
    if not np.isfinite(result[["open", "high", "low", "close", "volume"]].to_numpy()).all():
        raise ValueError("OHLCV values must be finite numbers")
    if (result["volume"] < 0).any():
        raise ValueError("Candle volume cannot be negative")
    result["spread_points"] = pd.to_numeric(result["spread_points"], errors="coerce")
    if (result["spread_points"].dropna() < 0).any():
        raise ValueError("Spread points cannot be negative")
    if ((result["high"] < result["low"]) |
            (result["high"] < result[["open", "close"]].max(axis=1)) |
            (result["low"] > result[["open", "close"]].min(axis=1))).any():
        raise ValueError("Each candle must satisfy low <= open/close <= high")
    result = result.sort_values("time", kind="stable").drop_duplicates("time", keep="last").reset_index(drop=True)
    normalized = result[["time", "open", "high", "low", "close", "volume", "spread_points"]]
    normalized.attrs.update(metadata)
    return normalized


def load_csv_candles(path: str | Path, start_iso: str | None = None,
                     end_iso: str | None = None) -> pd.DataFrame:
    """Load a CSV containing time, open, high, low, close, and optional volume."""
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Candle CSV does not exist: {source}")
    data = normalize_candles(pd.read_csv(source))
    return _date_slice(data, start_iso, end_iso)


def load_mt5_candles(symbol: str, timeframe: str, start_iso: str, end_iso: str) -> pd.DataFrame:
    """Fetch historical bars through the configured MT5 client."""
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe {timeframe!r}; choose from {sorted(SUPPORTED_TIMEFRAMES)}")
    start, end = _parse_datetime(start_iso), _parse_datetime(end_iso)
    if len(end_iso) == 10:
        end += timedelta(days=1, microseconds=-1)
    if start >= end:
        raise ValueError("start_iso must be earlier than end_iso")
    from .mt5_client import get_client

    client = get_client()
    data = client.get_candles_range(symbol, timeframe, start, end)
    if data is None or data.empty:
        raise ValueError(f"MT5 returned no {timeframe} candles for {symbol} in the requested range")
    normalized = normalize_candles(data)
    symbol_info = client.get_symbol_info(symbol)
    if symbol_info is None or float(symbol_info.get("point", 0)) <= 0:
        raise ValueError(f"MT5 did not provide a valid point size for {symbol}")
    normalized.attrs.update({
        "tick_size": float(symbol_info["point"]),
        "trade_tick_size": float(symbol_info.get("trade_tick_size") or symbol_info["point"]),
        "tick_value_per_lot": float(
            symbol_info.get("trade_tick_value_loss")
            or symbol_info.get("trade_tick_value")
            or symbol_info.get("trade_tick_value_profit")
            or 0
        ),
        "minimum_volume": float(symbol_info["min_volume"]),
        "maximum_volume": float(symbol_info["max_volume"]),
        "volume_step": float(symbol_info["min_volume_step"]),
        "broker_stops_level_points": float(symbol_info.get("min_stop_distance") or 0),
        "contract_size": float(symbol_info.get("contract_size") or 0),
        "leverage": float((client.get_account_info() or {}).get("leverage", 0)),
        "commission_per_lot_per_side": float(
            FILTERS.get("commission_per_lot_per_side", {}).get(symbol, 0)
        ),
        "fallback_spread_points": float(
            FILTERS.get("default_spread_points", {}).get(
                symbol, FILTERS.get("default_spread_points", {}).get("default", 0)
            )
        ),
        "slippage_points_per_fill": float(FILTERS["backtest_slippage_points_per_fill"]),
    })
    return normalized


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date_slice(data: pd.DataFrame, start_iso: str | None, end_iso: str | None) -> pd.DataFrame:
    if start_iso:
        data = data[data["time"] >= pd.Timestamp(_parse_datetime(start_iso))]
    if end_iso:
        end = _parse_datetime(end_iso)
        if len(end_iso) == 10:
            end += timedelta(days=1, microseconds=-1)
        data = data[data["time"] <= pd.Timestamp(end)]
    if len(data) < 30:
        raise ValueError("The selected date range contains fewer than 30 candles")
    return data.reset_index(drop=True)


def _resample_ohlcv(data: pd.DataFrame, rule: str) -> pd.DataFrame:
    indexed = data.set_index("time")
    result = indexed.resample(rule, label="right", closed="left", origin="start_day").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return result.dropna(subset=["open", "high", "low", "close"]).reset_index()


def _confirmed_pivots(data: pd.DataFrame, lookback: int) -> list[dict[str, Any]]:
    highs = data["high"].to_numpy()
    lows = data["low"].to_numpy()
    pivots: list[dict[str, Any]] = []
    for confirmed_at in range(lookback * 2, len(data)):
        pivot_index = confirmed_at - lookback
        left, right = pivot_index - lookback, pivot_index + lookback + 1
        high_slice, low_slice = highs[left:right], lows[left:right]
        if highs[pivot_index] >= high_slice.max() and np.count_nonzero(high_slice == highs[pivot_index]) == 1:
            pivots.append({"index": pivot_index, "confirmed_at": confirmed_at,
                           "price": float(highs[pivot_index]), "kind": "high"})
        if lows[pivot_index] <= low_slice.min() and np.count_nonzero(low_slice == lows[pivot_index]) == 1:
            pivots.append({"index": pivot_index, "confirmed_at": confirmed_at,
                           "price": float(lows[pivot_index]), "kind": "low"})
    return sorted(pivots, key=lambda pivot: (pivot["confirmed_at"], pivot["index"]))


def _market_bias(data: pd.DataFrame, lookback: int) -> tuple[list[str], list[dict[str, Any]]]:
    """Causal H4 HH/HL or LH/LL bias and confirmed pivot events."""
    source = _resample_ohlcv(data, "4h")
    pivots = _confirmed_pivots(source, lookback)
    by_confirmation: dict[int, list[dict[str, Any]]] = {}
    for pivot in pivots:
        by_confirmation.setdefault(pivot["confirmed_at"], []).append(pivot)
    highs: list[float] = []
    lows: list[float] = []
    state: list[str] = []
    last_bias = "neutral"
    for index in range(len(source)):
        for pivot in by_confirmation.get(index, []):
            if pivot["kind"] == "high":
                highs.append(pivot["price"])
            else:
                lows.append(pivot["price"])
        if len(highs) >= 2 and len(lows) >= 2:
            if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                last_bias = "bullish"
            elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                last_bias = "bearish"
            else:
                last_bias = "neutral"
        state.append(last_bias)

    higher_times = pd.to_datetime(source["time"], utc=True).astype("int64").to_numpy()
    base_times = pd.to_datetime(data["time"], utc=True).astype("int64").to_numpy()
    indices = np.searchsorted(higher_times, base_times, side="right") - 1
    biases = [state[index] if index >= 0 else "neutral" for index in indices]
    base_pivots = _confirmed_pivots(data, lookback)
    return biases, base_pivots


def _profile_levels(window: pd.DataFrame, value_area_pct: float) -> dict[str, float]:
    """Calculate rolling tick-volume POC/VAL/VAH from OHLC range overlap."""
    low = float(window["low"].min())
    high = float(window["high"].max())
    if high <= low:
        return {"poc": low, "val": low, "vah": high}
    bins = 32
    width = (high - low) / bins
    bar_lows = window["low"].to_numpy(dtype=float)
    bar_highs = window["high"].to_numpy(dtype=float)
    bar_volumes = window["volume"].to_numpy(dtype=float)
    bin_lows = low + np.arange(bins) * width
    bin_highs = bin_lows + width
    spans = bar_highs - bar_lows
    overlap = np.maximum(
        0.0,
        np.minimum(bar_highs[:, None], bin_highs[None, :])
        - np.maximum(bar_lows[:, None], bin_lows[None, :]),
    )
    volumes = np.sum(
        np.divide(
            bar_volumes[:, None] * overlap,
            spans[:, None],
            out=np.zeros_like(overlap),
            where=spans[:, None] > 0,
        ),
        axis=0,
    )
    flat_bars = spans <= 0
    flat_slots = np.clip(((bar_lows[flat_bars] - low) / width).astype(int), 0, bins - 1)
    np.add.at(volumes, flat_slots, bar_volumes[flat_bars])
    total = float(volumes.sum())
    if total <= 0:
        raise ValueError("FRVP lookback window contains no tick volume")
    poc_index = int(np.argmax(volumes))
    lower = upper = poc_index
    enclosed = volumes[poc_index]
    while enclosed < value_area_pct * total and (lower > 0 or upper < bins - 1):
        below = volumes[lower - 1] if lower > 0 else -1
        above = volumes[upper + 1] if upper < bins - 1 else -1
        if below >= above and lower > 0:
            lower -= 1
            enclosed += volumes[lower]
        elif upper < bins - 1:
            upper += 1
            enclosed += volumes[upper]
        else:
            lower -= 1
            enclosed += volumes[lower]
    return {
        "poc": low + (poc_index + 0.5) * width,
        "val": low + lower * width,
        "vah": low + (upper + 1) * width,
    }


def _engulfing(data: pd.DataFrame, index: int, direction: str) -> bool:
    if index < 1:
        return False
    previous, current = data.iloc[index - 1], data.iloc[index]
    if direction == "bullish":
        return (previous.close < previous.open and current.close > current.open
                and current.open <= previous.close and current.close >= previous.open)
    return (previous.close > previous.open and current.close < current.open
            and current.open >= previous.close and current.close <= previous.open)


def _in_session(timestamp: pd.Timestamp, start_hour: int, end_hour: int) -> bool:
    hour = timestamp.hour + timestamp.minute / 60
    within = start_hour <= hour < end_hour if start_hour < end_hour else hour >= start_hour or hour < end_hour
    if not within:
        return False
    opens = FILTERS["avoid_session_opens_first_minutes"]
    if opens["enabled"]:
        minute_of_day = timestamp.hour * 60 + timestamp.minute
        for key in ("london_open_utc", "newyork_open_utc"):
            start, end = opens[key]
            start_minute = _hour_minute(start)
            end_minute = _hour_minute(end)
            if start_minute <= minute_of_day < end_minute:
                return False
    friday_after = _hour_minute(FILTERS["avoid_friday_after"])
    sunday_before = _hour_minute(FILTERS["avoid_sunday_before"])
    if timestamp.weekday() == 4 and timestamp.hour * 60 + timestamp.minute >= friday_after:
        return False
    if timestamp.weekday() == 6 and timestamp.hour * 60 + timestamp.minute < sunday_before:
        return False
    return True


def _hour_minute(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _candidate_setups(
    data: pd.DataFrame, index: int, bias: str, pivots: Sequence[dict[str, Any]],
    parameters: BacktestParameters, point_size: float,
    order_blocks: list[dict[str, Any]],
    latest_confirmed: tuple[dict[str, Any] | None, dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    row = data.iloc[index]
    previous = data.iloc[index - 1]
    direction = bias
    candidates: list[dict[str, Any]] = []

    # BOS + immediate prior-bar liquidity sweep, matching the currently configured primary trigger.
    bullish_sweep = row.low < previous.low and row.close > row.open
    bearish_sweep = row.high > previous.high and row.close < row.open
    if latest_confirmed is None:
        known_pivots = [p for p in pivots if p["confirmed_at"] < index]
        latest_high = next((p for p in reversed(known_pivots) if p["kind"] == "high"), None)
        latest_low = next((p for p in reversed(known_pivots) if p["kind"] == "low"), None)
    else:
        latest_high, latest_low = latest_confirmed
    if (direction == "bullish" and bullish_sweep and latest_high and row.close > latest_high["price"]):
        candidates.append({"setup_type": "bos_liquidity_sweep", "direction": "long",
                           "features": {"bias": bias, "sweep": True, "bos_level": latest_high["price"]}})
    if (direction == "bearish" and bearish_sweep and latest_low and row.close < latest_low["price"]):
        candidates.append({"setup_type": "bos_liquidity_sweep", "direction": "short",
                           "features": {"bias": bias, "sweep": True, "bos_level": latest_low["price"]}})

    # A newly confirmed break anchors a deterministic OB proxy; the full discretionary validity
    # criteria remain visible in the stored features for later qualitative review.
    for pivot, side in ((latest_high, "bullish"), (latest_low, "bearish")):
        if pivot is None or row.close == pivot["price"]:
            continue
        broken = row.close > pivot["price"] if side == "bullish" else row.close < pivot["price"]
        already = any(zone["pivot_index"] == pivot["index"] for zone in order_blocks)
        if not broken or already:
            continue
        start = max(pivot["index"] + 1, index - 20)
        for candle_index in range(index - 1, start - 1, -1):
            candle = data.iloc[candle_index]
            opposite = candle.close < candle.open if side == "bullish" else candle.close > candle.open
            if opposite:
                order_blocks.append({
                    "pivot_index": pivot["index"], "created_at": index,
                    "direction": side, "low": float(candle.low), "high": float(candle.high),
                    "mitigations": 0, "volume": float(candle.volume),
                })
                break

    active_blocks = []
    for block in order_blocks:
        if block["direction"] == "bullish" and row.close < block["low"]:
            continue
        if block["direction"] == "bearish" and row.close > block["high"]:
            continue
        active_blocks.append(block)
        touched = row.low <= block["high"] and row.high >= block["low"]
        if (block["created_at"] < index and touched and block["direction"] == bias
                and _engulfing(data, index, bias)):
            block["mitigations"] += 1
            candidates.append({
                "setup_type": "order_block_retest",
                "direction": "long" if bias == "bullish" else "short",
                "features": {
                    "bias": bias, "ob_age_bars": index - block["created_at"],
                    "ob_mitigation_count": block["mitigations"],
                    "ob_range_points": (block["high"] - block["low"]) / point_size,
                    "ob_volume": block["volume"], "bos": True,
                    "liquidity_sweep": bullish_sweep if bias == "bullish" else bearish_sweep,
                },
            })
    order_blocks[:] = active_blocks

    lookback = parameters.frvp_lookback_period
    if (bias in {"bullish", "bearish"} and index >= lookback
            and _engulfing(data, index, bias)):
        levels = _profile_levels(data.iloc[index - lookback:index], parameters.value_area_pct)
        touched = [
            level for level in ("poc", "val", "vah")
            if row.low <= levels[level] <= row.high
        ]
        if touched:
            level = next((name for name in ("poc", "val", "vah") if name in touched))
            candidates.append({
                "setup_type": f"frvp_{level}_retest",
                "direction": "long" if bias == "bullish" else "short",
                "features": {"bias": bias, "frvp_level": level, **levels,
                             "frvp_lookback_period": lookback, "engulfing": True},
            })
    return candidates


def _make_trade_plan(
    data: pd.DataFrame, index: int, candidate: Mapping[str, Any],
    pivots: Sequence[dict[str, Any]], parameters: BacktestParameters, point_size: float,
) -> dict[str, Any]:
    direction = candidate["direction"]
    entry = float(data.iloc[index].close)
    past = [p for p in pivots if p["confirmed_at"] < index]
    if direction == "long":
        stops = [p["price"] for p in past if p["kind"] == "low" and p["price"] < entry]
        targets = sorted(
            (p["price"] for p in past if p["kind"] == "high" and p["price"] > entry)
        )
        if not stops:
            stops = [float(data.iloc[max(0, index - 10):index].low.min())]
        stop = max(stops) - parameters.sl_buffer_points * point_size
        stop_distance = entry - stop
        target_rrs = [(target, (target - entry) / stop_distance)
                      for target in targets if stop_distance > 0]
    else:
        stops = [p["price"] for p in past if p["kind"] == "high" and p["price"] > entry]
        targets = sorted(
            (p["price"] for p in past if p["kind"] == "low" and p["price"] < entry),
            reverse=True,
        )
        if not stops:
            stops = [float(data.iloc[max(0, index - 10):index].high.max())]
        stop = min(stops) + parameters.sl_buffer_points * point_size
        stop_distance = stop - entry
        target_rrs = [(target, (entry - target) / stop_distance)
                      for target in targets if stop_distance > 0]
    acceptable = [
        (target, rr) for target, rr in target_rrs
        if parameters.minimum_rr <= rr <= parameters.maximum_rr
    ]
    target, rr = acceptable[0] if acceptable else (
        target_rrs[0] if target_rrs else (None, 0.0)
    )
    risk = abs(entry - stop)
    reason = None
    if target is None:
        reason = "no_confirmed_structural_target"
    elif not acceptable:
        reason = "below_minimum_rr" if rr < parameters.minimum_rr else "above_maximum_rr"
    return {
        "entry_price": entry, "stop_loss": stop, "take_profit": target,
        "risk_distance": risk, "rr_ratio": rr, "rejection_reason": reason,
        "structural_target_candidates": [
            {"price": price, "rr": candidate_rr} for price, candidate_rr in target_rrs
        ],
    }


def run_backtest(
    candles: pd.DataFrame, symbol: str, timeframe: str = "M15",
    parameters: Mapping[str, Any] | BacktestParameters | None = None,
    initial_balance: float = 10_000.0,
    evaluation_start: int = 0,
    evaluation_end: int | None = None,
) -> dict[str, Any]:
    """Run causal candle-by-candle simulation. Same-bar SL/TP ambiguity resolves to SL."""
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe {timeframe!r}")
    if initial_balance <= 0:
        raise ValueError("initial_balance must be positive")
    data = normalize_candles(candles)
    if len(data) < 30:
        raise ValueError("At least 30 candles are required for a backtest")
    params = parameters if isinstance(parameters, BacktestParameters) else BacktestParameters.from_mapping(parameters)
    end_index = len(data) if evaluation_end is None else min(evaluation_end, len(data))
    if not 0 <= evaluation_start < end_index:
        raise ValueError("evaluation_start must be before evaluation_end and within candle data")
    derived_point = params.tick_size or float(data.attrs.get("tick_size", 0)) or _infer_tick_size(data)
    broker_values = {
        "tick_size": derived_point,
        "minimum_volume": data.attrs.get("minimum_volume", params.minimum_volume),
        "maximum_volume": min(
            float(RISK_MANAGEMENT["max_single_trade_lots"]),
            float(data.attrs.get("maximum_volume", params.maximum_volume)),
        ),
        "volume_step": data.attrs.get("volume_step", params.volume_step),
        "broker_stops_level_points": data.attrs.get(
            "broker_stops_level_points", params.broker_stops_level_points
        ),
        "contract_size": data.attrs.get("contract_size", params.contract_size),
        "leverage": data.attrs.get("leverage", params.leverage),
        "tick_value_per_lot": (
            float(data.attrs.get("tick_value_per_lot") or params.tick_value_per_lot)
        ),
        "commission_per_lot_per_side": data.attrs.get(
            "commission_per_lot_per_side", params.commission_per_lot_per_side
        ),
        "fallback_spread_points": data.attrs.get(
            "fallback_spread_points", params.fallback_spread_points
        ),
        "slippage_points_per_fill": data.attrs.get(
            "slippage_points_per_fill", params.slippage_points_per_fill
        ),
    }
    params = BacktestParameters.from_mapping({**asdict(params), **broker_values})
    biases, pivots = _market_bias(data, params.swing_lookback)
    pivots_by_confirmation: dict[int, list[dict[str, Any]]] = {}
    for pivot in pivots:
        pivots_by_confirmation.setdefault(pivot["confirmed_at"], []).append(pivot)
    latest_confirmed: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
    last_high = last_low = None
    for confirmed_at in range(len(data)):
        latest_confirmed.append((last_high, last_low))
        for pivot in pivots_by_confirmation.get(confirmed_at, []):
            if pivot["kind"] == "high":
                last_high = pivot
            else:
                last_low = pivot
    balance = float(initial_balance)
    equity_curve = [balance] * evaluation_start
    setups: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    order_blocks: list[dict[str, Any]] = []
    open_trade: dict[str, Any] | None = None
    consecutive_losses = 0
    current_day: str | None = None
    day_start_balance = balance
    daily_halted = False
    daily_risk_limit = float(RISK_MANAGEMENT["max_daily_risk_percent"])
    cooldown_until = -1

    for index in range(evaluation_start, end_index):
        row = data.iloc[index]
        day = row.time.date().isoformat()
        if day != current_day:
            current_day = day
            day_start_balance = balance
            daily_halted = False
            consecutive_losses = 0
        spread_points = (
            float(row.spread_points)
            if pd.notna(row.spread_points)
            else params.fallback_spread_points
        )
        spread_price = spread_points * derived_point
        if open_trade is not None and index > open_trade["entry_index"]:
            long_side = open_trade["direction"] == "long"
            stop_hit = row.low <= open_trade["stop_loss"] if long_side else row.high >= open_trade["stop_loss"]
            if not long_side:
                stop_hit = row.high + spread_price >= open_trade["stop_loss"]
            target_hit = (
                row.high >= open_trade["take_profit"] if long_side
                else row.low + spread_price <= open_trade["take_profit"]
            )
            if stop_hit or target_hit:
                exit_reason = "stop_loss" if stop_hit else "take_profit"
                level = open_trade["stop_loss"] if stop_hit else open_trade["take_profit"]
                slip_price = params.slippage_points_per_fill * derived_point
                if long_side:
                    exit_price = level - slip_price
                    price_pnl = exit_price - open_trade["entry_price"]
                else:
                    exit_price = level + spread_price + slip_price
                    price_pnl = open_trade["entry_price"] - exit_price
                gross_pnl = price_pnl * open_trade["cash_per_price_per_lot"] * open_trade["volume"]
                exit_commission = params.commission_per_lot_per_side * open_trade["volume"]
                entry_commission = open_trade["entry_commission"]
                pnl = gross_pnl - entry_commission - exit_commission
                result_r = pnl / open_trade["risk_amount"] if open_trade["risk_amount"] else 0.0
                balance += pnl
                trade = {**open_trade, "exit_time": row.time.isoformat(), "exit_price": float(exit_price),
                         "exit_reason": exit_reason, "result_r": float(result_r), "pnl": float(pnl),
                         "spread_points_at_exit": spread_points,
                         "exit_commission": exit_commission,
                         "balance_after": float(balance), "outcome": "win" if pnl > 0 else "loss"}
                trades.append(trade)
                open_trade = None
                if day_start_balance > 0 and (
                    day_start_balance - balance
                ) / day_start_balance * 100 >= daily_risk_limit:
                    daily_halted = True
                if pnl < 0:
                    consecutive_losses += 1
                    if consecutive_losses >= int(
                        RISK_MANAGEMENT["consecutive_loss_tracking"]["consecutive_losses_threshold"]
                    ):
                        daily_halted = True
                    cooldown_until = index + int(FILTERS["post_stop_loss_cooldown"]["cooldown_candles"]) + 1
                else:
                    consecutive_losses = 0

        if open_trade is None and index >= max(2 * params.swing_lookback, params.frvp_lookback_period + 1):
            if (index >= cooldown_until
                    and not daily_halted
                    and balance > 0
                    and _in_session(row.time, params.session_start_hour, params.session_end_hour)):
                candidates = _candidate_setups(
                    data, index, biases[index], pivots, params, derived_point,
                    order_blocks, latest_confirmed[index],
                )
                for candidate in candidates:
                    plan = _make_trade_plan(data, index, candidate, pivots, params, derived_point)
                    max_spread = float(
                        FILTERS.get("maximum_spread_points", {}).get(symbol, float("inf"))
                    )
                    if spread_points > max_spread:
                        plan["rejection_reason"] = "spread_above_configured_maximum"
                    long_side = candidate["direction"] == "long"
                    slip_price = params.slippage_points_per_fill * derived_point
                    entry_price = (
                        float(row.close) + spread_price + slip_price
                        if long_side else float(row.close) - slip_price
                    )
                    plan["signal_entry_price"] = plan["entry_price"]
                    plan["entry_price"] = entry_price
                    plan["spread_points_at_entry"] = spread_points
                    plan["entry_slippage_points"] = params.slippage_points_per_fill
                    plan["stop_distance"] = abs(entry_price - float(plan["stop_loss"]))
                    min_stop = max(
                        params.broker_stops_level_points * derived_point,
                        float(data.attrs.get("trade_tick_size", derived_point)),
                    )
                    if plan["stop_distance"] + 1e-12 < min_stop:
                        plan["rejection_reason"] = "stop_below_broker_minimum_distance"
                    if plan.get("take_profit") is not None:
                        plan["target_distance"] = abs(float(plan["take_profit"]) - entry_price)
                        if plan["target_distance"] + 1e-12 < min_stop:
                            plan["rejection_reason"] = "target_below_broker_minimum_distance"

                    adverse_stop = (
                        float(plan["stop_loss"]) - slip_price
                        if long_side
                        else float(plan["stop_loss"]) + spread_price + slip_price
                    )
                    cash_per_price_per_lot = params.tick_value_per_lot / float(
                        data.attrs.get("trade_tick_size", derived_point)
                    )
                    loss_per_lot = abs(entry_price - adverse_stop) * cash_per_price_per_lot
                    entry_commission = params.commission_per_lot_per_side
                    exit_commission = params.commission_per_lot_per_side
                    loss_per_lot += entry_commission + exit_commission
                    risk_budget = balance * params.risk_percent / 100.0
                    raw_volume = min(
                        risk_budget / loss_per_lot if loss_per_lot > 0 else 0.0,
                        params.maximum_volume,
                    )
                    volume = math.floor((raw_volume + 1e-12) / params.volume_step) * params.volume_step
                    volume = round(volume, 8)
                    plan["risk_budget"] = risk_budget
                    plan["loss_per_lot_at_stop"] = loss_per_lot
                    plan["volume"] = volume
                    plan["volume_step"] = params.volume_step
                    plan["risk_amount"] = volume * loss_per_lot
                    plan["margin_required"] = (
                        entry_price * params.contract_size * volume / params.leverage
                    )
                    plan["commission_per_lot_per_side"] = params.commission_per_lot_per_side
                    plan["slippage_points_per_fill"] = params.slippage_points_per_fill
                    if volume + 1e-12 < params.minimum_volume:
                        plan["rejection_reason"] = "minimum_volume_exceeds_risk_budget"
                    if plan["margin_required"] > balance:
                        plan["rejection_reason"] = "insufficient_backtest_margin"
                    if plan.get("take_profit") is not None and loss_per_lot > 0:
                        favorable_target = (
                            float(plan["take_profit"]) - slip_price
                            if long_side
                            else float(plan["take_profit"]) + spread_price + slip_price
                        )
                        reward_per_lot = (
                            favorable_target - entry_price if long_side
                            else entry_price - favorable_target
                        ) * cash_per_price_per_lot - entry_commission - exit_commission
                        net_rr = reward_per_lot / loss_per_lot
                        plan["rr_ratio"] = net_rr
                    else:
                        net_rr = 0.0
                    setup = {
                        "setup_time": row.time.isoformat(), "symbol": symbol, "timeframe": timeframe,
                        "setup_type": candidate["setup_type"], "direction": candidate["direction"],
                        "features": candidate["features"], **plan,
                    }
                    rejection = plan.get("rejection_reason")
                    if rejection:
                        pass
                    elif plan["risk_distance"] <= 0:
                        rejection = "invalid_stop_distance"
                    elif plan["take_profit"] is None:
                        rejection = "no_confirmed_structural_target"
                    elif plan["rr_ratio"] < params.minimum_rr:
                        rejection = "below_minimum_rr"
                    elif plan["rr_ratio"] > params.maximum_rr:
                        rejection = "above_maximum_rr"
                    setup["status"] = "rejected" if rejection else "entered"
                    setup["rejection_reason"] = rejection
                    if rejection:
                        setups.append(setup)
                        continue
                    open_trade = {
                        **setup, "entry_index": index, "entry_time": row.time.isoformat(),
                        "risk_percent": params.risk_percent,
                        "minimum_rr": params.minimum_rr, "maximum_rr": params.maximum_rr,
                        "parameters": asdict(params),
                        "cash_per_price_per_lot": cash_per_price_per_lot,
                        "entry_commission": entry_commission * volume,
                    }
                    setups.append(setup)
                    break
        marked_equity = balance
        if open_trade is not None:
            direction_sign = 1 if open_trade["direction"] == "long" else -1
            slippage_price = params.slippage_points_per_fill * derived_point
            liquidation_price = (
                float(row.close) - slippage_price
                if direction_sign == 1
                else float(row.close) + spread_price + slippage_price
            )
            unrealized_pnl = (
                (liquidation_price - open_trade["entry_price"])
                * open_trade["cash_per_price_per_lot"] * open_trade["volume"]
                if direction_sign == 1
                else (open_trade["entry_price"] - liquidation_price)
                * open_trade["cash_per_price_per_lot"] * open_trade["volume"]
            )
            unrealized_pnl -= (
                open_trade["entry_commission"]
                + params.commission_per_lot_per_side * open_trade["volume"]
            )
            marked_equity += unrealized_pnl
        equity_curve.append(marked_equity)

    if open_trade is not None:
        last = data.iloc[end_index - 1]
        direction_sign = 1 if open_trade["direction"] == "long" else -1
        spread_points = (
            float(last.spread_points) if pd.notna(last.spread_points)
            else params.fallback_spread_points
        )
        spread_price = spread_points * derived_point
        slippage_price = params.slippage_points_per_fill * derived_point
        exit_price = (
            float(last.close) - slippage_price if direction_sign == 1
            else float(last.close) + spread_price + slippage_price
        )
        price_pnl = (
            exit_price - open_trade["entry_price"] if direction_sign == 1
            else open_trade["entry_price"] - exit_price
        )
        pnl = (
            price_pnl * open_trade["cash_per_price_per_lot"] * open_trade["volume"]
            - open_trade["entry_commission"]
            - params.commission_per_lot_per_side * open_trade["volume"]
        )
        result_r = pnl / open_trade["risk_amount"] if open_trade["risk_amount"] else 0.0
        balance += pnl
        trades.append({
            **open_trade, "exit_time": last.time.isoformat(), "exit_price": float(exit_price),
            "exit_reason": "end_of_data", "result_r": float(result_r), "pnl": float(pnl),
            "spread_points_at_exit": spread_points,
            "balance_after": float(balance), "outcome": "win" if pnl > 0 else "loss",
        })
        equity_curve[-1] = balance

    metrics = _summarize(trades, initial_balance, balance, equity_curve)
    by_setup: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        by_setup.setdefault(trade["setup_type"], []).append(trade)
    metrics["by_setup_type"] = {name: _summarize(rows, initial_balance, initial_balance + sum(t["pnl"] for t in rows), [])
                                for name, rows in sorted(by_setup.items())}
    return {
        "symbol": symbol, "timeframe": timeframe,
        "start_time": data.iloc[evaluation_start].time.isoformat(),
        "end_time": data.iloc[end_index - 1].time.isoformat(),
        "bars": end_index - evaluation_start, "initial_balance": initial_balance,
        "final_balance": balance, "parameters": asdict(params),
        "metrics": metrics, "setups": setups, "trades": trades,
        "methodology": {
            "entry": "H4 HH/HL or LH/LL bias; confirmed structure+sweep, OB retest, or rolling FRVP engulfing retest",
            "stop": "Most recent causally confirmed opposing swing with configurable point buffer",
            "target": "Nearest causally confirmed opposing swing; trades without a target or minimum R:R are rejected",
            "risk": "Fixed percentage of current balance; daily drawdown cap and two-loss consecutive circuit breaker stop entries",
            "daily_limit": f"Stop new entries after realized daily drawdown reaches {daily_risk_limit:g}% of UTC day-start balance",
            "intrabar_tie": "If stop and target both touch in one bar, stop is assumed first",
            "frvp_volume": "MT5 tick volume proxy distributed across OHLC price range",
            "discretionary_logic": "Order blocks use a logged deterministic proxy; review OB quality qualitatively",
        },
    }


def _infer_tick_size(data: pd.DataFrame) -> float:
    values = np.unique(data[["open", "high", "low", "close"]].to_numpy().ravel())
    differences = np.diff(np.sort(values))
    positive = differences[differences > 0]
    return float(np.min(positive)) if len(positive) else 0.0001


def _summarize(trades: Sequence[Mapping[str, Any]], initial_balance: float,
               final_balance: float, equity: Sequence[float]) -> dict[str, Any]:
    if not trades:
        return {"trade_count": 0, "win_rate": 0.0, "expectancy_r": 0.0,
                "profit_factor": 0.0, "max_drawdown_pct": 0.0,
                "net_return_pct": (final_balance / initial_balance - 1) * 100,
                "total_pnl": final_balance - initial_balance}
    results = np.asarray([float(trade["result_r"]) for trade in trades])
    pnls = np.asarray([float(trade["pnl"]) for trade in trades])
    gains, losses = float(pnls[pnls > 0].sum()), float(-pnls[pnls < 0].sum())
    if equity:
        curve = np.asarray(equity, dtype=float)
    else:
        curve = np.concatenate(([initial_balance], initial_balance + np.cumsum(pnls)))
    peaks = np.maximum.accumulate(curve)
    drawdown = np.max(np.divide(peaks - curve, peaks, out=np.zeros_like(peaks), where=peaks != 0))
    return {
        "trade_count": len(trades), "win_rate": float(np.mean(pnls > 0) * 100),
        "expectancy_r": float(results.mean()), "profit_factor": gains / losses if losses else None,
        "max_drawdown_pct": float(drawdown * 100),
        "net_return_pct": (final_balance / initial_balance - 1) * 100,
        "total_pnl": float(pnls.sum()),
    }


def _grid_values(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    if not grid:
        raise ValueError("At least one grid parameter must be supplied")
    fields = set(BacktestParameters.__dataclass_fields__)
    unknown = set(grid) - fields
    if unknown:
        raise ValueError(f"Unknown optimization parameter(s): {', '.join(sorted(unknown))}")
    names = list(grid)
    choices = [list(grid[name]) for name in names]
    if any(not values for values in choices):
        raise ValueError("Optimization grid values cannot be empty")
    combinations = list(itertools.product(*choices))
    if len(combinations) > 500:
        raise ValueError(f"Grid has {len(combinations)} combinations; maximum is 500")
    return [dict(zip(names, values)) for values in combinations]


def walk_forward_optimize(
    candles: pd.DataFrame, symbol: str, timeframe: str = "M15",
    grid: Mapping[str, Sequence[Any]] | None = None, folds: int = 3,
    initial_balance: float = 10_000.0,
) -> dict[str, Any]:
    """Expanding-window search with separate, chronological out-of-sample windows."""
    data = normalize_candles(candles)
    if folds < 1 or folds > 10:
        raise ValueError("folds must be from 1 through 10")
    default_grid = {
        "minimum_rr": [2.0, 3.0], "risk_percent": [1.0, 2.0],
        "session_start_hour": [7, 9], "session_end_hour": [16, 21],
        "frvp_lookback_period": [50, 100], "sl_buffer_points": [0.0, 5.0],
    }
    combinations = _grid_values(grid or default_grid)
    minimum_train = max(30, int(len(data) * 0.5))
    remaining = len(data) - minimum_train
    if remaining < folds:
        raise ValueError("Not enough bars for the requested walk-forward folds")
    test_size = remaining // folds
    folds_result = []
    selected: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    validation_data = data.copy()
    validation_data["time"] = pd.to_datetime(validation_data["time"], utc=True)

    for fold in range(folds):
        test_start = minimum_train + fold * test_size
        test_end = len(data) if fold == folds - 1 else min(len(data), test_start + test_size)
        # Warm up indicators and positions with past-only bars, but measure only this
        # fold's holdout. Candidate rules see history through the test boundary.
        context_start = max(
            0,
            test_start - max(_TIMEFRAME_MINUTES[timeframe], 20_000, int(len(data) * 0.1)),
        )
        fold_data = validation_data.iloc[context_start:test_end].reset_index(drop=True)
        local_test_start = test_start - context_start
        local_test_end = test_end - context_start
        train_rows = []
        for combination in combinations:
            params = BacktestParameters.from_mapping(combination)
            training = run_backtest(
                validation_data, symbol, timeframe, params, initial_balance, 0, test_start
            )
            metrics = training["metrics"]
            score = float(metrics["expectancy_r"] - max(0.0, metrics["max_drawdown_pct"] - 20.0) / 100)
            train_rows.append((score, combination, metrics))
            evaluations.append({"fold": fold + 1, "parameters": combination,
                                "training_metrics": metrics, "training_score": score})
        _, best_parameters, training_metrics = max(train_rows, key=lambda row: (row[0], row[2]["trade_count"]))
        out = run_backtest(
            fold_data, symbol, timeframe, best_parameters, initial_balance,
            local_test_start, local_test_end,
        )
        selected.append(best_parameters)
        folds_result.append({
            "fold": fold + 1, "train_start": data.iloc[0].time.isoformat(),
            "train_end": data.iloc[test_start - 1].time.isoformat(),
            "test_start": validation_data.iloc[test_start].time.isoformat(),
            "test_end": validation_data.iloc[test_end - 1].time.isoformat(),
            "selected_parameters": best_parameters, "training_metrics": training_metrics,
            "out_of_sample_metrics": out["metrics"],
        })
    test_metrics = [fold["out_of_sample_metrics"] for fold in folds_result]
    avg_expectancy = float(np.mean([metrics["expectancy_r"] for metrics in test_metrics]))
    counts = Counter(json.dumps(item, sort_keys=True) for item in selected)
    proposal = max(counts, key=counts.get)
    proposed_parameters = json.loads(proposal)
    return {
        "symbol": symbol, "timeframe": timeframe, "bars": len(data), "folds": folds_result,
        "grid_combinations": len(combinations), "evaluations": evaluations,
        "out_of_sample_average": {
            "win_rate": float(np.mean([m["win_rate"] for m in test_metrics])),
            "expectancy_r": avg_expectancy,
            "max_drawdown_pct": float(np.mean([m["max_drawdown_pct"] for m in test_metrics])),
            "trade_count": sum(m["trade_count"] for m in test_metrics),
        },
        "proposal": {
            "parameters": proposed_parameters, "status": "pending_approval",
            "positive_out_of_sample_expectancy": avg_expectancy > 0,
            "folds_selected": sum(item == proposed_parameters for item in selected),
            "note": "Proposal only. Live strategy configuration is unchanged.",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Causal SMC + FRVP backtester")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="M15", choices=sorted(SUPPORTED_TIMEFRAMES))
    parser.add_argument("--csv", help="OHLCV CSV; otherwise fetch from MT5")
    parser.add_argument("--start", default=(datetime.now(timezone.utc) - timedelta(days=730)).date().isoformat())
    parser.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--initial-balance", type=float, default=10_000.0)
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--parameters", default="{}", help="JSON object of backtest parameter overrides")
    parser.add_argument("--grid", default="{}", help="JSON parameter grid; optimization only")
    args = parser.parse_args(argv)

    candles = load_csv_candles(args.csv, args.start, args.end) if args.csv else load_mt5_candles(
        args.symbol, args.timeframe, args.start, args.end
    )
    if args.optimize:
        grid = json.loads(args.grid)
        if not isinstance(grid, dict):
            raise ValueError("--grid must be a JSON object")
        result = walk_forward_optimize(candles, args.symbol, args.timeframe, grid or None,
                                       args.folds, args.initial_balance)
        from .backtest_store import BacktestStore

        record_id = BacktestStore().save_optimization(result)
        summary = {
            "proposal_id": record_id, "status": "pending_approval",
            "out_of_sample_average": result["out_of_sample_average"],
            "proposal": result["proposal"], "grid_combinations": result["grid_combinations"],
        }
    else:
        parameters = json.loads(args.parameters)
        if not isinstance(parameters, dict):
            raise ValueError("--parameters must be a JSON object")
        result = run_backtest(candles, args.symbol, args.timeframe, parameters,
                              args.initial_balance)
        from .backtest_store import BacktestStore

        record_id = BacktestStore().save_backtest(result)
        summary = {
            "run_id": record_id, "metrics": result["metrics"],
            "setup_type_metrics": result["metrics"]["by_setup_type"],
            "setups_logged": len(result["setups"]), "trades_logged": len(result["trades"]),
        }
    if args.output:
        Path(args.output).write_text(
            json.dumps(result, default=_json_default, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        summary["output_path"] = str(Path(args.output).resolve())
    summary["log_database"] = str(BacktestStore().database_path)
    printable = json.dumps(summary, default=_json_default, indent=2, allow_nan=False)
    print(printable)
    return 0


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


if __name__ == "__main__":
    raise SystemExit(main())
