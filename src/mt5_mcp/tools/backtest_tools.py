"""Backtesting, optimizer approval, and review-dataset MCP tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from ..backtesting import (
    BacktestParameters,
    load_csv_candles,
    load_mt5_candles,
    run_backtest as execute_backtest,
    walk_forward_optimize,
)
from ..backtest_store import BacktestStore

_store: BacktestStore | None = None


def _get_store() -> BacktestStore:
    global _store
    if _store is None:
        _store = BacktestStore()
    return _store


def _load_input(
    symbol: str, timeframe: str, csv_path: str | None,
    start_iso: str | None, end_iso: str | None,
):
    if csv_path:
        return load_csv_candles(csv_path, start_iso or None, end_iso or None)
    end = end_iso or datetime.now(timezone.utc).isoformat()
    start = start_iso or (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()
    return load_mt5_candles(symbol, timeframe, start, end)


def _parse_json_object(raw: str, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def run_backtest(
    symbol: str,
    timeframe: str = "M15",
    csv_path: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    initial_balance: float = 10_000.0,
    parameters_json: str = "{}",
) -> dict[str, Any]:
    """Run the current causal SMC/FRVP rules on CSV or the configured MT5 account's history."""
    candles = _load_input(symbol, timeframe, csv_path, start_iso, end_iso)
    parameters = BacktestParameters.from_mapping(_parse_json_object(parameters_json, "parameters_json"))
    result = execute_backtest(candles, symbol, timeframe, parameters, initial_balance)
    store = _get_store()
    run_id = store.save_backtest(result)
    return {
        "run_id": run_id, "symbol": symbol, "timeframe": timeframe,
        "start_time": result["start_time"], "end_time": result["end_time"],
        "bars": result["bars"], "metrics": result["metrics"],
        "setup_type_metrics": result["metrics"]["by_setup_type"],
        "setups_logged": len(result["setups"]), "trades_logged": len(result["trades"]),
        "parameters": result["parameters"], "methodology": result["methodology"],
        "log_database": str(store.database_path),
    }


def optimize_backtest(
    symbol: str,
    timeframe: str = "M15",
    csv_path: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    grid_json: str = "{}",
    folds: int = 3,
    initial_balance: float = 10_000.0,
) -> dict[str, Any]:
    """Grid-search numeric thresholds with expanding-window out-of-sample validation."""
    candles = _load_input(symbol, timeframe, csv_path, start_iso, end_iso)
    grid = _parse_json_object(grid_json, "grid_json")
    result = walk_forward_optimize(
        candles, symbol, timeframe, grid or None, folds, initial_balance
    )
    store = _get_store()
    proposal_id = store.save_optimization(result)
    return {
        "proposal_id": proposal_id, "status": "pending_approval",
        "symbol": symbol, "timeframe": timeframe, "bars": result["bars"],
        "grid_combinations": result["grid_combinations"],
        "out_of_sample_average": result["out_of_sample_average"],
        "folds": result["folds"], "proposal": result["proposal"],
        "live_config_changed": False,
    }


def list_optimizer_proposals(include_decided: bool = False) -> dict[str, Any]:
    """List optimizer recommendations; pending approval is the default."""
    return {"proposals": _get_store().get_proposals(include_decided)}


def approve_optimizer_proposal(
    proposal_id: str, confirm: bool = False, note: str = "",
) -> dict[str, Any]:
    """Approve or reject a proposal without editing the live strategy configuration."""
    if not confirm:
        raise ValueError("Set confirm=true after reviewing the proposal to record an approval decision")
    if not note.strip():
        raise ValueError("Add a brief approval note describing the human review")
    return _get_store().decide_proposal(proposal_id, approve=True, note=note.strip())


def reject_optimizer_proposal(
    proposal_id: str, confirm: bool = False, note: str = "",
) -> dict[str, Any]:
    """Reject a pending optimizer proposal; live strategy configuration is unchanged."""
    if not confirm:
        raise ValueError("Set confirm=true to record the rejection")
    return _get_store().decide_proposal(proposal_id, approve=False, note=note.strip())


def import_live_trade_log(csv_path: str) -> dict[str, Any]:
    """Import closed live/demo trade history into the canonical local review schema."""
    return _get_store().import_live_csv(csv_path)


def export_backtest_review_bundle(
    output_path: str | None = None,
    run_id: str | None = None,
    include_live: bool = True,
    max_rows: int = 2_000,
) -> dict[str, Any]:
    """Export setup features, labels, trade outcomes, and live logs for LLM review/training."""
    return _get_store().export_review_bundle(
        Path(output_path).expanduser() if output_path else None,
        run_id=run_id,
        include_live=include_live,
        max_rows=max_rows,
    )
