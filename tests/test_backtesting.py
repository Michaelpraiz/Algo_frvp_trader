import csv
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from mt5_mcp import backtesting
from mt5_mcp.backtest_store import BacktestStore


def candle_frame(count=120):
    times = pd.date_range("2026-01-05T07:00:00Z", periods=count, freq="15min")
    close = 100 + np.sin(np.arange(count) / 3) * 0.5 + np.arange(count) * 0.01
    opened = close - np.where(np.arange(count) % 2, 0.1, -0.1)
    return pd.DataFrame({
        "time": times,
        "open": opened,
        "high": np.maximum(opened, close) + 0.2,
        "low": np.minimum(opened, close) - 0.2,
        "close": close,
        "tick_volume": np.full(count, 100),
    })


def test_normalize_sorts_deduplicates_and_rejects_invalid_ohlc():
    data = candle_frame(30).iloc[[2, 0, 1, 1]].copy()
    result = backtesting.normalize_candles(data)
    assert result["time"].is_monotonic_increasing
    assert len(result) == 3
    data.loc[data.index[0], "high"] = 0
    with pytest.raises(ValueError, match="low <= open/close <= high"):
        backtesting.normalize_candles(data)


def test_mt5_tick_size_metadata_survives_normalization():
    data = candle_frame()
    data.attrs["tick_size"] = 0.01
    normalized = backtesting.normalize_candles(data)
    assert normalized.attrs["tick_size"] == 0.01


def test_confirmed_pivots_are_delayed_until_right_side_closes():
    frame = pd.DataFrame({
        "high": [1, 2, 5, 2, 1, 1, 1],
        "low": [0, 0, 0, 0, 0, 0, 0],
    })
    pivots = backtesting._confirmed_pivots(frame, lookback=2)
    high = next(pivot for pivot in pivots if pivot["kind"] == "high")
    assert high["index"] == 2
    assert high["confirmed_at"] == 4


def test_backtest_uses_conservative_same_bar_exit_and_persists_label(monkeypatch, tmp_path):
    data = candle_frame(60)
    entry_index = 24
    data.loc[entry_index + 1, ["high", "low"]] = [104.0, 98.0]
    monkeypatch.setattr(
        backtesting, "_market_bias",
        lambda candles, lookback: (["bullish"] * len(candles), []),
    )

    def candidates(candles, index, bias, pivots, params, point_size, zones, latest_confirmed=None):
        if index == entry_index:
            return [{"setup_type": "frvp_poc_retest", "direction": "long",
                     "features": {"bias": bias, "frvp_level": "poc"}}]
        return []

    monkeypatch.setattr(backtesting, "_candidate_setups", candidates)
    monkeypatch.setattr(
        backtesting, "_make_trade_plan",
        lambda candles, index, candidate, pivots, params, point_size: {
            "entry_price": float(candles.iloc[index].close), "stop_loss": 99.0,
            "take_profit": 103.0, "risk_distance": 1.0, "rr_ratio": 3.0,
            "rejection_reason": "above_maximum_rr",
        },
    )
    result = backtesting.run_backtest(
        data, "GOLD#", parameters={"frvp_lookback_period": 10, "tick_size": 0.01}
    )
    assert result["metrics"]["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "stop_loss"
    assert result["trades"][0]["result_r"] == -1
    assert result["metrics"]["by_setup_type"]["frvp_poc_retest"]["win_rate"] == 0

    store = BacktestStore(tmp_path / "backtest.sqlite3")
    run_id = store.save_backtest(result)
    bundle_path = tmp_path / "review.json"
    summary = store.export_review_bundle(bundle_path, run_id=run_id, include_live=False)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert summary["setup_count"] == 1
    assert bundle["setups"][0]["outcome_label"] == 0
    assert bundle["trades"][0]["exit_reason"] == "stop_loss"


def test_consecutive_losses_do_not_halt_but_daily_loss_cap_does(monkeypatch):
    data = candle_frame(60)
    entry_index = 21
    data.loc[entry_index + 1:, "low"] = 98.0
    monkeypatch.setattr(
        backtesting, "_market_bias",
        lambda candles, lookback: (["bullish"] * len(candles), []),
    )
    monkeypatch.setattr(
        backtesting, "_candidate_setups",
        lambda *args, **kwargs: [{"setup_type": "test", "direction": "long", "features": {}}],
    )
    monkeypatch.setattr(
        backtesting, "_make_trade_plan",
        lambda candles, index, candidate, pivots, params, point_size: {
            "entry_price": float(candles.iloc[index].close), "stop_loss": 99.0,
            "take_profit": 103.0, "risk_distance": 1.0, "rr_ratio": 3.0,
        },
    )

    result = backtesting.run_backtest(
        data, "GOLD#", parameters={"frvp_lookback_period": 10, "tick_size": 0.01}
    )
    assert result["metrics"]["trade_count"] >= 3
    assert all(trade["outcome"] == "loss" for trade in result["trades"])
    assert sum(trade["pnl"] for trade in result["trades"]) >= -1_000
    assert all(trade["risk_amount"] <= trade["risk_budget"] + 0.01
               for trade in result["trades"])


def test_backtest_accepts_configured_maximum_rr_and_rejects_higher_value():
    params = backtesting.BacktestParameters.from_mapping({"maximum_rr": 29.44})
    assert params.maximum_rr == 29.44
    with pytest.raises(ValueError, match="29.44"):
        backtesting.BacktestParameters.from_mapping({"maximum_rr": 29.45})


def test_walk_forward_creates_pending_proposal_and_explicit_approval(tmp_path):
    grid = {
        "minimum_rr": [3.0], "risk_percent": [1.0],
        "session_start_hour": [7], "session_end_hour": [21],
        "frvp_lookback_period": [10], "sl_buffer_points": [0.0],
    }
    result = backtesting.walk_forward_optimize(
        candle_frame(), "GOLD#", grid=grid, folds=2
    )
    assert len(result["folds"]) == 2
    assert result["proposal"]["status"] == "pending_approval"
    store = BacktestStore(tmp_path / "optimizer.sqlite3")
    proposal_id = store.save_optimization(result)
    proposal = store.get_proposals()[0]
    assert proposal["proposal_id"] == proposal_id
    assert proposal["status"] == "pending_approval"
    decision = store.decide_proposal(proposal_id, approve=True, note="Reviewed OOS folds")
    assert decision["status"] == "approved"
    assert decision["live_config_changed"] is False
    assert store.get_proposals() == []
    with pytest.raises(ValueError, match="already been approved"):
        store.decide_proposal(proposal_id, approve=True, note="duplicate")


def test_live_trade_import_and_review_export(tmp_path):
    path = tmp_path / "live.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticket", "symbol", "type", "time", "profit"])
        writer.writeheader()
        writer.writerow({
            "ticket": "42", "symbol": "GOLD#", "type": "BUY",
            "time": "2026-01-05T14:00:00Z", "profit": "25.5",
        })
    store = BacktestStore(tmp_path / "live.sqlite3")
    assert store.import_live_csv(path)["imported"] == 1
    output = tmp_path / "bundle.json"
    store.export_review_bundle(output, include_live=True)
    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert bundle["live_trades"][0]["outcome_label"] == 1
    assert bundle["review_prompt"]
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
        store.import_live_csv(path)
