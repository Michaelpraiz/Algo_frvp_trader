import math
from datetime import datetime, timezone
import numpy as np

from mt5_mcp.trade_engine import TradeEngine
from mt5_mcp.frvp import FRVPStore, compute_frvp


class DummyClient:
    def __init__(self, candles):
        self.candles = candles

    def get_candles(self, symbol, timeframe, count):
        return self.candles

    def get_tick(self, symbol):
        return {'bid': self.candles['close'][-1], 'ask': self.candles['close'][-1]}


class DummyFRVPProvider:
    TIMEFRAMES = {'M1': 1, 'M5': 5, 'M15': 15, 'M30': 30, 'H1': 60, 'H4': 240, 'D1': 1440}

    def symbol_info(self, symbol):
        return type('SymbolInfo', (), {'point': 0.1})()

    def copy_rates_range(self, symbol, timeframe, start, end):
        count = 4 if timeframe == 1 else 8
        dtype = [
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), ('low', 'f8'),
            ('close', 'f8'), ('tick_volume', 'f8'),
        ]
        rates = np.zeros(count, dtype=dtype)
        for index in range(count):
            rates[index] = (index, 100 + index, 103 + index, 99 + index, 102 + index, 100)
        return rates


def build_candles():
    n = 80
    closes = []
    opens = []
    highs = []
    lows = []
    times = []

    base = 100.0
    for i in range(n):
        o = base + i * 0.2
        drift = 0.8 if i < 40 else -0.8
        c = o + drift
        h = max(o, c) + 1.2
        l = min(o, c) - 1.2
        closes.append(c)
        opens.append(o)
        highs.append(h)
        lows.append(l)
        times.append(i)
    return {
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'time': times,
    }


def test_bos_contract_and_frvp_contract():
    engine = TradeEngine()
    engine.client = DummyClient(build_candles())

    result = engine.detect_bos_choch('XAUUSD', 'H1')
    assert 'trend_state' in result
    assert 'events' in result
    assert 'bos_done' in result
    assert 'status' in result

    frvp = engine.find_frvp_levels('XAUUSD', 'H1')
    assert 'poc' in frvp
    assert 'vah' in frvp
    assert 'val' in frvp
    assert 'retest_rule' in frvp


def test_ob_contract_returns_all_and_visible_layers():
    engine = TradeEngine()
    engine.client = DummyClient(build_candles())

    result = engine.find_order_blocks('XAUUSD', 'H1')
    assert 'all_tracked_obs' in result
    assert 'visible_obs' in result
    assert 'valid_count' in result
    assert isinstance(result['all_tracked_obs'], list)
    assert isinstance(result['visible_obs'], list)


def test_frvp_uses_tick_volume_and_retains_prior_levels():
    provider = DummyFRVPProvider()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    result = compute_frvp('XAUUSD', start, end, provider=provider)

    assert result.timeframe_used == 'M1'
    assert result.total_volume == 400
    assert result.val <= result.poc <= result.vah
    assert result.profile

    store = FRVPStore()
    store.add('XAUUSD', result)
    assert len(store.as_dict('XAUUSD')) == 1
