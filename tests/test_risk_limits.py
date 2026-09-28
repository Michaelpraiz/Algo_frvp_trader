from types import SimpleNamespace

from mt5_mcp import risk_manager
from mt5_mcp.tools import order_tools


def test_loss_streak_is_tracked_without_halt():
    manager = risk_manager.RiskManager.__new__(risk_manager.RiskManager)
    manager.risk_per_trade = 3.0
    manager.consecutive_losses = 0
    manager.daily_stats = risk_manager.DailyStats()

    manager.record_trade_outcome(-100.0)
    result = manager.record_trade_outcome(-100.0)

    assert result["consecutive_losses"] == 2
    assert result["trading_halted"] is False
    assert result["loss_reduction_active"] is False


def test_order_is_rejected_when_risk_exceeds_remaining_daily_budget(monkeypatch):
    symbol_info = SimpleNamespace(
        point=0.01,
        trade_tick_size=0.01,
        volume_step=0.01,
        volume_min=0.01,
        volume_max=10.0,
        trade_stops_level=0,
    )
    monkeypatch.setattr(order_tools, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(order_tools.mt5, "symbol_info", lambda symbol: symbol_info)
    monkeypatch.setattr(
        order_tools.mt5, "symbol_info_tick",
        lambda symbol: SimpleNamespace(bid=100.0, ask=100.1),
    )
    monkeypatch.setattr(
        order_tools.mt5, "account_info",
        lambda: SimpleNamespace(balance=10_000.0),
    )
    monkeypatch.setattr(order_tools.mt5, "order_calc_profit", lambda *args: -200.0)
    monkeypatch.setattr(
        order_tools, "get_risk_manager",
        lambda: SimpleNamespace(check_daily_drawdown=lambda: {
            "can_trade": True,
            "daily_pnl": -900.0,
            "day_start_balance": 10_000.0,
        }),
    )

    result = order_tools._validate_broker_order(
        "test", "GOLD#", "buy", 0.1, 100.0, 99.0, 102.0
    )

    assert result is not None
    assert "remaining daily loss budget $100.00" in result["error"]
