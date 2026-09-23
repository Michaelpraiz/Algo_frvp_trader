"""Fixed Range Volume Profile for the Gold SMC + FRVP strategy.

The MT5 API exposes tick volume rather than traded volume. This module uses
that tick volume proxy and keeps the calculator independent from the MT5
connection wrapper so it can be tested with a fake provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Protocol, Tuple

import MetaTrader5 as mt5
import numpy as np

logger = logging.getLogger(__name__)

TIMEFRAME_CASCADE: Tuple[str, ...] = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
_TIMEFRAME_VALUES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


class MT5RatesProvider(Protocol):
    def copy_rates_range(self, symbol: str, timeframe: Any, start: datetime, end: datetime) -> Any:
        ...

    def symbol_info(self, symbol: str) -> Any:
        ...


@dataclass
class FRVPResult:
    poc: float
    val: float
    vah: float
    profile: Dict[float, float]
    timeframe_used: str
    total_volume: float
    anchor_time: datetime
    end_time: datetime
    range_high: float
    range_low: float
    value_area_pct: float = 0.70
    tick_size: float = 0.0
    bin_width: float = 0.0
    total_bars: int = 0
    error: Optional[str] = None


@dataclass
class ExtendedFRVPLevel:
    """A prior leg's levels retained for forward retest checks."""

    symbol: str
    anchor_time: datetime
    end_time: datetime
    poc: float
    val: float
    vah: float
    timeframe_used: str
    active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class FRVPStore:
    """Retain current and prior leg profiles for forward level retests."""

    def __init__(self) -> None:
        self._profiles: Dict[str, List[ExtendedFRVPLevel]] = {}

    def add(self, symbol: str, result: FRVPResult, **metadata: Any) -> ExtendedFRVPLevel:
        level = ExtendedFRVPLevel(
            symbol=symbol,
            anchor_time=result.anchor_time,
            end_time=result.end_time,
            poc=result.poc,
            val=result.val,
            vah=result.vah,
            timeframe_used=result.timeframe_used,
            metadata=metadata,
        )
        self._profiles.setdefault(symbol, []).append(level)
        return level

    def levels(self, symbol: str, active_only: bool = True) -> List[ExtendedFRVPLevel]:
        profiles = self._profiles.get(symbol, [])
        if active_only:
            return [profile for profile in profiles if profile.active]
        return list(profiles)

    def as_dict(self, symbol: str, active_only: bool = True) -> List[Dict[str, Any]]:
        return [_level_to_dict(level) for level in self.levels(symbol, active_only)]

    def clear(self, symbol: Optional[str] = None) -> None:
        if symbol is None:
            self._profiles.clear()
        else:
            self._profiles.pop(symbol, None)


class FRVPError(ValueError):
    """Raised when an anchored profile cannot be calculated."""


def _as_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rates_frame(rates: Any) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if rates is None or len(rates) == 0:
        raise FRVPError("No MT5 bars returned for the requested anchor range")
    names = getattr(rates, "dtype", None)
    fields = names.names if names is not None else None
    if fields is None or not {"open", "high", "low", "close", "tick_volume"}.issubset(fields):
        raise FRVPError("MT5 rates must contain open, high, low, close, and tick_volume")
    times = np.asarray(rates["time"])
    opens = np.asarray(rates["open"], dtype=float)
    highs = np.asarray(rates["high"], dtype=float)
    lows = np.asarray(rates["low"], dtype=float)
    closes = np.asarray(rates["close"], dtype=float)
    volumes = np.asarray(rates["tick_volume"], dtype=float)
    return times, opens, highs, lows, closes, volumes


def _select_rates(
    provider: MT5RatesProvider,
    symbol: str,
    anchor_time: datetime,
    end_time: datetime,
    max_bars: int,
    structure_timeframe: Optional[str],
) -> Tuple[Any, str]:
    first_nonempty: Optional[Tuple[Any, str]] = None
    for timeframe in TIMEFRAME_CASCADE:
        rates = provider.copy_rates_range(symbol, _TIMEFRAME_VALUES[timeframe], anchor_time, end_time)
        if rates is None or len(rates) == 0:
            continue
        if first_nonempty is None:
            first_nonempty = (rates, timeframe)
        if len(rates) < max_bars:
            return rates, timeframe

    if structure_timeframe and structure_timeframe in _TIMEFRAME_VALUES:
        rates = provider.copy_rates_range(
            symbol, _TIMEFRAME_VALUES[structure_timeframe], anchor_time, end_time
        )
        if rates is not None and len(rates) > 0:
            return rates, structure_timeframe

    if first_nonempty is not None:
        return first_nonempty
    raise FRVPError("No MT5 bars returned for any FRVP timeframe")


def _ticks_per_row(range_size: float, tick_size: float, row_mode: str, row_size: float) -> int:
    if tick_size <= 0 or row_size <= 0:
        raise FRVPError("tick_size and row_size must be positive")
    if row_mode == "ticks_per_row":
        ticks = max(1, int(round(row_size)))
        if math.ceil(range_size / (ticks * tick_size)) < 3:
            return max(1, math.ceil(range_size / (10 * tick_size)))
        return ticks
    if row_mode != "num_rows":
        raise FRVPError("row_mode must be 'ticks_per_row' or 'num_rows'")

    requested_rows = max(3, int(round(row_size)))
    raw = max(1.0, range_size / (requested_rows * tick_size))
    candidates = {max(1, math.floor(raw)), max(1, math.ceil(raw))}
    return min(
        candidates,
        key=lambda ticks: (abs(math.ceil(range_size / (ticks * tick_size)) - requested_rows), -math.ceil(range_size / (ticks * tick_size))),
    )


def _build_profile(
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    range_low: float,
    range_high: float,
    bin_width: float,
) -> Dict[float, float]:
    bin_count = max(1, int(math.ceil((range_high - range_low) / bin_width)))
    profile = {range_low + index * bin_width: 0.0 for index in range(bin_count)}
    for bar_low, bar_high, volume in zip(lows, highs, volumes):
        if bar_high <= bar_low:
            index = min(bin_count - 1, max(0, int((bar_low - range_low) / bin_width)))
            key = range_low + index * bin_width
            profile[key] += float(volume)
            continue
        first = max(0, int(math.floor((bar_low - range_low) / bin_width)))
        last = min(bin_count - 1, int(math.floor((bar_high - range_low) / bin_width)))
        bar_range = bar_high - bar_low
        for index in range(first, last + 1):
            bin_low = range_low + index * bin_width
            bin_high = bin_low + bin_width
            overlap = max(0.0, min(bar_high, bin_high) - max(bar_low, bin_low))
            if overlap:
                profile[bin_low] += float(volume) * overlap / bar_range
    return profile


def _value_area(profile: Dict[float, float], value_area_pct: float, bin_width: float) -> Tuple[float, float, float]:
    prices = list(profile)
    volumes = list(profile.values())
    poc_index = max(range(len(prices)), key=lambda index: (volumes[index], prices[index]))
    target = sum(volumes) * value_area_pct
    enclosed = volumes[poc_index]
    low_index = high_index = poc_index
    while enclosed < target and (low_index > 0 or high_index < len(prices) - 1):
        below = volumes[low_index - 1] if low_index > 0 else -1.0
        above = volumes[high_index + 1] if high_index < len(prices) - 1 else -1.0
        if below >= above and low_index > 0:
            low_index -= 1
            enclosed += volumes[low_index]
        elif high_index < len(prices) - 1:
            high_index += 1
            enclosed += volumes[high_index]
        else:
            low_index -= 1
            enclosed += volumes[low_index]
    return (
        prices[poc_index] + bin_width / 2,
        prices[low_index],
        prices[high_index] + bin_width,
    )


def compute_frvp(
    symbol: str,
    anchor_time: datetime,
    end_time: datetime,
    value_area_pct: float = 0.70,
    max_bars: int = 5000,
    row_mode: str = "ticks_per_row",
    row_size: float = 10,
    structure_timeframe: Optional[str] = None,
    provider: Optional[MT5RatesProvider] = None,
) -> FRVPResult:
    """Compute one fixed-range profile from an SMC structural leg."""
    if not 0 < value_area_pct <= 1:
        raise FRVPError("value_area_pct must be between 0 and 1")
    if max_bars < 1:
        raise FRVPError("max_bars must be positive")
    anchor_time = _as_datetime(anchor_time)
    end_time = _as_datetime(end_time)
    if end_time < anchor_time:
        raise FRVPError("end_time must be at or after anchor_time")
    provider = provider or mt5
    info = provider.symbol_info(symbol)
    tick_size = float(getattr(info, "point", 0.0) if info is not None else 0.0)
    if tick_size <= 0:
        raise FRVPError(f"Unable to determine tick size for {symbol}")

    rates, timeframe_used = _select_rates(
        provider, symbol, anchor_time, end_time, max_bars, structure_timeframe
    )
    _, opens, highs, lows, closes, volumes = _rates_frame(rates)
    del opens, closes
    range_low = float(np.min(lows))
    range_high = float(np.max(highs))
    range_size = range_high - range_low
    if range_size <= 0:
        price = float(np.mean(highs))
        total_volume = float(np.sum(volumes))
        return FRVPResult(
            price, price, price, {price: total_volume}, timeframe_used, total_volume,
            anchor_time, end_time, range_high, range_low, value_area_pct, tick_size, 0.0, len(highs)
        )

    ticks = _ticks_per_row(range_size, tick_size, row_mode, row_size)
    bin_width = ticks * tick_size
    profile = _build_profile(highs, lows, volumes, range_low, range_high, bin_width)
    total_volume = float(sum(profile.values()))
    if total_volume <= 0:
        raise FRVPError("The anchored bars contain no tick volume")
    poc, val, vah = _value_area(profile, value_area_pct, bin_width)
    return FRVPResult(
        poc=poc,
        val=val,
        vah=vah,
        profile=profile,
        timeframe_used=timeframe_used,
        total_volume=total_volume,
        anchor_time=anchor_time,
        end_time=end_time,
        range_high=range_high,
        range_low=range_low,
        value_area_pct=value_area_pct,
        tick_size=tick_size,
        bin_width=bin_width,
        total_bars=len(highs),
    )


def _level_to_dict(level: ExtendedFRVPLevel) -> Dict[str, Any]:
    return {
        "symbol": level.symbol,
        "anchor_time": level.anchor_time.isoformat(),
        "end_time": level.end_time.isoformat(),
        "poc": level.poc,
        "val": level.val,
        "vah": level.vah,
        "timeframe_used": level.timeframe_used,
        "active": level.active,
        **level.metadata,
    }


def result_to_dict(result: FRVPResult) -> Dict[str, Any]:
    return {
        "poc": result.poc,
        "val": result.val,
        "vah": result.vah,
        "profile": result.profile,
        "timeframe_used": result.timeframe_used,
        "total_volume": result.total_volume,
        "anchor_time": result.anchor_time.isoformat(),
        "end_time": result.end_time.isoformat(),
        "range_high": result.range_high,
        "range_low": result.range_low,
        "value_area_pct": result.value_area_pct,
        "tick_size": result.tick_size,
        "bin_width": result.bin_width,
        "total_bars": result.total_bars,
        "error": result.error,
    }
