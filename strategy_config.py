# =============================================================================
# TRADING STRATEGY CONFIGURATION
# =============================================================================
# !! IMPORTANT: This is a DUMMY file pre-filled with an example SMC strategy.
# !! You MUST review and replace all values with your actual trading rules
# !! before connecting this to live trading.
# =============================================================================

STRATEGY_NAME = "Smart Money Concepts (SMC)"

# -----------------------------------------------------------------------------
# INSTRUMENTS
# -----------------------------------------------------------------------------
# TODO: Replace with your actual traded instruments
INSTRUMENTS = [
    "EURUSD",   # Major Forex pair
    "GBPUSD",   # Major Forex pair
    "XAUUSD",   # Gold
    "US30",     # Dow Jones Index
    "NAS100",   # Nasdaq 100
]

# -----------------------------------------------------------------------------
# TIMEFRAMES
# -----------------------------------------------------------------------------
# Analysis flows top-down: HTF for bias → MTF for structure → LTF for entry
# MT5 timeframe constants map: M1, M5, M15, M30, H1, H4, D1, W1

TIMEFRAMES = {
    "bias":     "D1",    # TODO: Your higher timeframe for overall market bias
    "structure":"H4",    # TODO: Your mid timeframe for market structure / BOS / CHoCH
    "entry":    "H1",    # TODO: Your execution timeframe for POI entry
    "confirm":  "M15",   # TODO: Your confirmation / trigger timeframe (optional)
}

# -----------------------------------------------------------------------------
# MARKET STRUCTURE RULES
# -----------------------------------------------------------------------------
# TODO: Adjust these rules to match exactly how YOU identify structure

MARKET_STRUCTURE = {
    # Break of Structure (BOS): continuation signal
    "bos": {
        "description": "Price breaks and closes beyond the last swing high (bullish) or low (bearish)",
        "confirmation": "Candle close beyond swing point, not just wick",
        "min_swing_size_pips": 20,  # TODO: Your minimum swing size to count as valid
    },

    # Change of Character (CHoCH): reversal signal
    "choch": {
        "description": "First structural break against the prevailing trend — signals potential reversal",
        "confirmation": "Must break the most recent higher low (bull) or lower high (bear)",
        "requires_liquidity_sweep": True,  # TODO: True if you require a sweep before CHoCH
    },

    # Swing point lookback
    "swing_lookback_candles": 10,  # TODO: How many candles left/right define a swing high/low
}

# -----------------------------------------------------------------------------
# ORDER BLOCKS (OB)
# -----------------------------------------------------------------------------
# TODO: Define how you identify and qualify order blocks

ORDER_BLOCKS = {
    "description": "Last bullish/bearish candle before a strong impulsive move that causes BOS",
    "types": ["bullish_ob", "bearish_ob"],
    "mitigation_type": "50_percent",  # TODO: Options: 'wick', '50_percent', 'open', 'close'
    "min_impulse_candles": 3,         # TODO: Minimum candles in the impulse move to qualify OB
    "invalidation": "candle_close_through",  # TODO: 'wick_through' or 'candle_close_through'
    "max_ob_age_candles": 50,         # TODO: How old an OB can be and still be valid
    "use_fvg_confluence": True,       # TODO: Require FVG overlap with OB for higher probability
}

# -----------------------------------------------------------------------------
# FAIR VALUE GAPS (FVG) / IMBALANCES
# -----------------------------------------------------------------------------
# TODO: Adjust FVG rules to match your model

FAIR_VALUE_GAPS = {
    "description": "3-candle pattern where candle 1 high and candle 3 low do not overlap (bullish), or vice versa (bearish)",
    "min_gap_pips": 5,        # TODO: Minimum gap size to qualify (filter out noise)
    "entry_zone": "50_percent",  # TODO: Where inside FVG you enter: 'top', '50_percent', 'bottom'
    "invalidation": "candle_close_through_entire_gap",
    "nested_fvg_priority": True,  # TODO: Prefer FVGs inside OBs for confluence
}

# -----------------------------------------------------------------------------
# LIQUIDITY CONCEPTS
# -----------------------------------------------------------------------------
# TODO: Define what liquidity targets you hunt / use for entries

LIQUIDITY = {
    "buy_side_liquidity": {
        "description": "Highs where retail stop losses cluster (equal highs, previous day high, session high)",
        "types": ["equal_highs", "previous_day_high", "asian_session_high", "swing_high"],
    },
    "sell_side_liquidity": {
        "description": "Lows where retail stop losses cluster",
        "types": ["equal_lows", "previous_day_low", "asian_session_low", "swing_low"],
    },
    "liquidity_sweep": {
        "description": "Price raids liquidity then reverses — key trigger for entry",
        "confirmation": "Wick through liquidity level, candle body closes back inside range",
        "require_before_entry": True,  # TODO: Do you require a sweep before entering a POI?
    }
}

# -----------------------------------------------------------------------------
# PREMIUM / DISCOUNT ZONES
# -----------------------------------------------------------------------------
# Based on the Fibonacci range of the current dealing range

PREMIUM_DISCOUNT = {
    "range_reference": "last_swing_high_to_low",  # TODO: What defines your dealing range
    "premium_zone_start": 0.5,   # Above 50% = premium (look for shorts)
    "discount_zone_start": 0.5,  # Below 50% = discount (look for longs)
    "optimal_entry_zone_bull": (0.618, 0.786),  # TODO: Your OTE for longs
    "optimal_entry_zone_bear": (0.618, 0.786),  # TODO: Your OTE for shorts
}

# -----------------------------------------------------------------------------
# SESSIONS
# -----------------------------------------------------------------------------
# TODO: Adjust to sessions you actually trade (all times in UTC)

SESSIONS = {
    "london": {
        "open": "07:00",
        "close": "10:00",
        "trade": True,   # TODO: Do you trade this session?
    },
    "new_york": {
        "open": "12:00",
        "close": "15:00",
        "trade": True,
    },
    "asian": {
        "open": "00:00",
        "close": "03:00",
        "trade": False,  # TODO: Asian session often used for liquidity hunting only
    },
    "killzones": {
        "london_open": ("07:00", "09:00"),
        "new_york_open": ("12:00", "14:00"),
        "london_close": ("15:00", "16:00"),
    }
}

# -----------------------------------------------------------------------------
# ENTRY RULES
# -----------------------------------------------------------------------------
# TODO: This is the most important section — be precise about YOUR entry checklist

ENTRY_RULES = {
    "bias_required": True,        # Must have H4/D1 directional bias before any entry
    "minimum_confluences": 2,     # TODO: Minimum number of confluence factors required

    "confluence_factors": [
        "price_at_OB",
        "price_at_FVG",
        "liquidity_swept",
        "in_discount_zone_for_longs",
        "in_premium_zone_for_shorts",
        "htf_poi_alignment",
        "session_killzone",
    ],

    "entry_triggers": [
        # TODO: Select which LTF triggers you use to pull the trigger
        "displacement_candle",       # Strong impulsive candle away from POI
        "market_structure_shift",    # LTF CHoCH/BOS confirming reversal from POI
        "engulfing_candle",
        "fvg_formation_at_poi",
    ],

    "entry_trigger_required": "market_structure_shift",  # TODO: Your primary trigger
}

# -----------------------------------------------------------------------------
# RISK MANAGEMENT
# -----------------------------------------------------------------------------
# !! CRITICAL: Fill this in accurately — this directly controls money

RISK_MANAGEMENT = {
    "risk_per_trade_percent": 1.0,    # TODO: % of account risked per trade (e.g. 0.5, 1.0, 2.0)
    "max_daily_drawdown_percent": 3.0, # TODO: Stop trading for the day if hit
    "max_open_trades": 3,             # TODO: Maximum concurrent positions
    "max_trades_per_day": 3,          # TODO: Hard daily trade limit

    "stop_loss": {
        "placement": "beyond_ob_wick",  # TODO: Options: 'beyond_ob_wick', 'beyond_swing', 'fixed_pips'
        "buffer_pips": 3,               # TODO: Extra buffer beyond structure
        "fixed_pips": None,             # TODO: Set if using fixed SL (overrides placement)
    },

    "take_profit": {
        "method": "liquidity_target",   # TODO: Options: 'liquidity_target', 'fixed_rr', 'structure'
        "rr_ratio": 3.0,                # TODO: Your target R:R (used if method is 'fixed_rr')
        "partials": [
            {"rr": 1.0, "close_percent": 33},  # TODO: Close 33% at 1R
            {"rr": 2.0, "close_percent": 33},  # TODO: Close another 33% at 2R
            # Remainder runs to liquidity target
        ],
        "move_to_breakeven_at_rr": 1.0,  # TODO: Move SL to BE when 1R is hit
    },

    "lot_sizing_method": "percent_risk",  # TODO: 'percent_risk', 'fixed_lot'
    "fixed_lot_size": 0.01,               # TODO: Used only if lot_sizing_method = 'fixed_lot'
}

# -----------------------------------------------------------------------------
# TRADE FILTERS (DO NOT TRADE IF...)
# -----------------------------------------------------------------------------
# TODO: Add/remove filters based on what you avoid

FILTERS = {
    "avoid_news_minutes_before": 30,     # TODO: Avoid trading X mins before high-impact news
    "avoid_news_minutes_after": 15,      # TODO: Avoid trading X mins after news
    "min_rr_to_take_trade": 2.0,         # TODO: Don't take trade if R:R is below this
    "avoid_friday_after": "18:00",       # TODO: UTC time — avoid holding over weekend
    "avoid_sunday_before": "21:00",      # TODO: UTC time — avoid thin Sunday open
    "avoid_choppy_market": True,         # TODO: Skip if price is ranging with no clear bias
    "spread_max_pips": {                 # TODO: Max acceptable spread per instrument
        "EURUSD": 1.5,
        "GBPUSD": 2.0,
        "XAUUSD": 30,
        "US30": 5,
        "NAS100": 5,
    }
}

# -----------------------------------------------------------------------------
# SYSTEM PROMPT CONTEXT (fed to Copilot/Claude via MCP)
# -----------------------------------------------------------------------------
# This is what the AI assistant will know about how you trade

STRATEGY_SYSTEM_PROMPT = f"""
You are an AI trading assistant for a Smart Money Concepts (SMC) trader.

STRATEGY OVERVIEW:
- Approach: Top-down analysis using institutional order flow concepts
- Core ideas: Order Blocks, Fair Value Gaps, Liquidity sweeps, Market Structure (BOS/CHoCH)
- Bias: Determined on {TIMEFRAMES['bias']} timeframe
- Structure: Mapped on {TIMEFRAMES['structure']} timeframe
- Entry: Executed on {TIMEFRAMES['entry']} with {TIMEFRAMES['confirm']} confirmation

INSTRUMENTS TRADED: {', '.join(INSTRUMENTS)}

TRADE LOGIC (in order):
1. Determine HTF bias (bullish/bearish) on {TIMEFRAMES['bias']}
2. Map key Order Blocks and FVGs on {TIMEFRAMES['structure']}
3. Wait for price to reach a POI (OB or FVG) in Premium (shorts) or Discount (longs)
4. Confirm a liquidity sweep at or before the POI
5. Wait for {ENTRY_RULES['entry_trigger_required']} on {TIMEFRAMES['entry']} or {TIMEFRAMES['confirm']}
6. Execute with SL beyond structure, TP at next liquidity target

RISK PER TRADE: {RISK_MANAGEMENT['risk_per_trade_percent']}% of account
MAX DAILY LOSS: {RISK_MANAGEMENT['max_daily_drawdown_percent']}%
MAX OPEN TRADES: {RISK_MANAGEMENT['max_open_trades']}

Always check filters before suggesting a trade. Never suggest entering during high-impact news.
Provide analysis in this format: Bias → Structure → POI → Confluence → Entry Trigger → SL → TP
"""
