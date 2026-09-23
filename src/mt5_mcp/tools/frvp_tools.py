"""MCP-facing FRVP tools for anchored SMC structural legs."""

from datetime import datetime
from typing import Any, Dict, Optional

from ..frvp import FRVPStore, compute_frvp, result_to_dict
_store = FRVPStore()


def compute_fixed_range_volume_profile(
    symbol: str,
    anchor_time: str,
    end_time: str,
    value_area_pct: float = 0.70,
    max_bars: int = 5000,
    row_mode: str = "ticks_per_row",
    row_size: float = 10,
    structure_timeframe: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute and retain an FRVP for one confirmed structural leg."""
    result = compute_frvp(
        symbol=symbol,
        anchor_time=datetime.fromisoformat(anchor_time),
        end_time=datetime.fromisoformat(end_time),
        value_area_pct=value_area_pct,
        max_bars=max_bars,
        row_mode=row_mode,
        row_size=row_size,
        structure_timeframe=structure_timeframe,
    )
    _store.add(symbol, result, source="confirmed_structural_leg")
    response = result_to_dict(result)
    response["extended_levels"] = _store.as_dict(symbol)
    return response


def get_extended_frvp_levels(symbol: str) -> Dict[str, Any]:
    """Return current and prior FRVP levels retained for retest detection."""
    return {"symbol": symbol, "levels": _store.as_dict(symbol)}
