# =============================================================================
# TRADING STRATEGY CONFIGURATION — PHASE 3
# =============================================================================
# Smart Money Concepts (SMC) Strategy with Structure-Based Entry System
# Updated June 2026: BOS + Liquidity Sweep Entry, Swing-Based SL, Dynamic Lot Sizing
# =============================================================================

STRATEGY_NAME = "Gold SMC + FRVP Master Strategy"

# -----------------------------------------------------------------------------
# INSTRUMENTS
# -----------------------------------------------------------------------------
# Gold-focused SMC + FRVP implementation with a bullish/bearish market structure engine.
INSTRUMENTS = [
    # === MAJOR PAIRS (7) ===
    "EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD", "USDCHF", "NZDUSD", 
    
    # === MAJOR PAIRS - VARIANTS ===
    "EURUSD#", "GBPUSD#", "AUDUSD#", "USDJPY#", "USDCAD#", "USDCHF#", "NZDUSD#",
    
    # === EUR CROSSES (6) ===
    "EURGBP#", "EURJPY#", "EURCHF#", "EURCAD#", "EURAUD#", "EURNZD#", 
    
    # === OTHER CROSSES (14) ===
    "GBPJPY#", "GBPCHF#", "GBPCAD#", "GBPAUD#", "GBPNZD#", "AUDJPY#", "AUDCHF#", "AUDCAD#", "AUDNZD#",  "CADJPY#", "CADCHF#", "CHFJPY#",
    "NZDJPY#", "NZDCHF#", "NZDCAD#", 
    
    # === METALS & CRYPTO (2) ===
    "GOLD#", "BTCUSD#",
]

# -----------------------------------------------------------------------------
# TIMEFRAMES
# -----------------------------------------------------------------------------
# Master strategy flow: H4 bias → H1/30m setup zone → M15/M5/M1 sniper entry
# MT5 timeframe constants map: M1, M5, M15, M30, H1, H4, D1, W1

TIMEFRAMES = {
    "bias":     "H4",     # Overall trend bias on the 4H timeframe
    "structure": "H1",     # Setup/structure zone (primary structure timeframe)
    "setup":    "M30",     # Secondary setup zone used by the 1H/30m FRVP model
    "entry":    "M15",     # Primary sniper entry timeframe
    "confirm":  ["M5", "M1"],  # Shorter confirmation / trigger timeframes
}

# =============================================================================
# MARKET STRUCTURE RULES (SMC Standard - Dynamic per Instrument)
# =============================================================================

MARKET_STRUCTURE = {
    "description": "Smart Money Concepts market structure analysis - Break of Structure (BOS) & Change of Character (CHoCH)",
    
    # Break of Structure (BOS): continuation signal
    "bos": {
        "description": "Price breaks and closes beyond the last swing high (bullish) or low (bearish)",
        "confirmation": "Candle close beyond swing point, not just wick",
        
        "min_swing_size_dynamic": {
            "rule": "Varies by instrument — no universal pip standard",
            "forex_majors": {"EURUSD": "15-20 pips", "GBPUSD": "20-25 pips", "USDJPY": "15-20 pips", "USDCAD": "15-20 pips", "USDCHF": "15-20 pips", "AUDUSD": "15-20 pips", "NZDUSD": "15-20 pips"},
            "crosses": {"EURGBP": "25-35 pips", "GBPJPY": "30-50 pips", "EURJPY": "25-35 pips", "AUDJPY": "25-35 pips"},
            "metals": {"GOLD": "150-300 pips", "SILVER": "50-100 pips"},
            "crypto": {"BTCUSD": "500-1000 pips"},
        },
        
        "fvg_displacement_requirement": {
            "critical_rule": "BOS must be caused by a displacement candle leaving an FVG — confirms institutional move",
            "validation_logic": "After BOS, scan the impulse candle(s) for a Fair Value Gap (3-candle imbalance)",
            "meaning": "If BOS has no FVG, it may be a false break or retail-driven move — less reliable",
            "application": "Prefer BOS entries where the impulse move creates an FVG in the direction of the break",
        },
    },

    # Change of Character (CHoCH): reversal signal
    "choch": {
        "description": "First structural break against the prevailing trend — signals potential reversal",
        "confirmation": "Must break the most recent higher low (bull) or lower high (bear)",
        "requires_liquidity_sweep": True,
        "definition": "In bullish structure: break of a lower high = first sign of reversal; in bearish structure: break of a higher low = first sign of reversal",
    },

    # Swing point identification
    "swing_identification": {
        "swing_high": "Candle with highest high compared to X candles left and right",
        "swing_low": "Candle with lowest low compared to X candles left and right",
        "lookback_candles": 10,
        "confirmatory_method": "After 5+ candles past potential swing, if no new extreme, it is confirmed",
    },
    
    "structural_integrity": {
        "rule": "Each confirmed swing must be of sufficient size (see min_swing_size_dynamic)",
        "purpose": "Filter out noise; only trade institutional-sized structure",
    },
}

# =============================================================================
# ORDER BLOCKS (OB) — SMC Standard Definition & Validation
# =============================================================================

ORDER_BLOCKS = {
    "description": "Last bullish/bearish candle before a strong impulsive move that causes BOS",
    "institutional_signal": "Identifies where smart money accumulated/distributed before impulse",
    
    "drawing_methods": {
        "method_1_body_only": {
            "description": "OB defined as open-to-close of the trigger candle",
            "use_case": "Cleaner zones, less whipsaw, preferred for tight structures",
            "boundary_high": "Close of trigger candle (for bearish OB)",
            "boundary_low": "Open of trigger candle (for bullish OB)",
        },
        "method_2_wick_inclusive": {
            "description": "OB defined as high-to-low of the trigger candle (includes wicks)",
            "use_case": "When OB candle has small body but long wicks — captures true institutional zone",
            "boundary_high": "High of trigger candle (for bearish OB)",
            "boundary_low": "Low of trigger candle (for bullish OB)",
            "decision_logic": "If wick is >2x the body size, use wick-inclusive; otherwise use body-only",
        },
    },
    
    "ob_types": {
        "bullish_ob": "Last bear candle before bullish impulse — acts as buy zone",
        "bearish_ob": "Last bull candle before bearish impulse — acts as sell zone",
    },
    
    "invalidation": {
        "method": "Price candle close beyond OB boundary",
        "bullish_ob_invalidation": "Candle close below lower boundary of OB = broken",
        "bearish_ob_invalidation": "Candle close above upper boundary of OB = broken",
        "mitigated_definition": "Price touches OB and reverses = mitigation, OB still valid",
    },
    
    "breaker_block_concept": {
        "definition": "When an OB is invalidated (candle closes through it) after a liquidity sweep, it becomes a breaker block",
        "polarity_flip": "Bullish OB → invalidated → becomes bearish breaker block (reverses polarity)",
        "high_probability": "Breaker blocks offer high-probability entries in the opposite direction",
        "application": "After OB is broken + liquidity swept, re-entries at breaker block often lead to strong moves",
    },
    
    "validity_age_rule": {
        "rule": "OB valid within 10 candles post-BOS on entry timeframe (M15/H1)",
        "replaced_by": "BOS retest timeout (10 candles) from FILTERS section",
        "reason": "If price doesn't retest/use OB within 10 candles of BOS, setup invalidates (fake breakout)",
        "measurement": "Candles on entry timeframe (15M or 1H per trade)",
    },
    
    "confluence_rules": {
        "ob_with_fvg": "If OB overlaps with an FVG in the direction of the impulse, confluence increases",
        "ob_retest": "Price touches OB, wicks back, then resumes — highest probability setup",
    },
}

# =============================================================================
# FAIR VALUE GAPS (FVG) / IMBALANCES — SMC Standard Validation
# =============================================================================

FAIR_VALUE_GAPS = {
    "description": "3-candle pattern where candle 1 high and candle 3 low do not overlap (bullish), or vice versa (bearish)",
    "institutional_signal": "Imbalances left behind by institutional moves — high-probability pullback targets",
    
    "min_gap_size_dynamic": {
        "rule": "Varies by instrument — no universal 5-pip standard",
        "forex_majors": {"EURUSD": "5-10 pips", "GBPUSD": "5-10 pips", "USDJPY": "5-10 pips"},
        "crosses": {"EURGBP": "10-15 pips", "GBPJPY": "15-25 pips", "EURJPY": "10-15 pips"},
        "metals": {"GOLD": "50-100 pips", "SILVER": "20-50 pips"},
        "crypto": {"BTCUSD": "200-500 pips"},
    },
    
    "invalidation_levels": {
        "level_1_weakened": {
            "trigger": "Price closes beyond 50% (CE = Common Equalizer) of FVG with no reversal reaction",
            "status": "FVG considered weakened — still valid but lower probability",
            "action": "Can still trade, but expect less reliable reversal at FVG boundary",
        },
        "level_2_fully_invalid": {
            "trigger": "Price candle closes beyond the far boundary (opposite side) of FVG",
            "status": "FVG fully invalidated — zone is broken and should not be traded",
            "action": "Discard FVG, do not use as entry or TP target",
        },
    },
    
    "fvg_validation_timeframe_rule": {
        "method": "Validate FVG on 4x lower timeframe",
        "example": "H4 FVG → confirm on H1; H1 FVG → confirm on M15; M15 FVG → confirm on M5",
        "logic": "If lower timeframe shows price cleanly filling the zone without reaction, FVG is false (reject entry)",
        "false_fvg_indicator": "Lower TF shows candles closing through gap cleanly = zone is not institutional",
    },
    
    "inversion_fvg_ifvg": {
        "definition": "When an FVG is fully invalidated (price closes through it), the zone flips polarity",
        "example": "Bullish FVG (imbalance above price) gets invalidated → becomes Bearish iFVG (imbalance below price)",
        "high_probability": "Inverted FVGs often trigger strong reversals in the opposite direction",
        "application": "After FVG invalidation, watch for iFVG at same zone as high-probability entry trigger",
    },
    
    "entry_zone": "50_percent",
    "nested_fvg_priority": True,
}

# =============================================================================
# LIQUIDITY CONCEPTS — Internal vs External (SMC Standard)
# =============================================================================

LIQUIDITY = {
    "overview": "Smart Money hunts retail stop losses (liquidity) before institutional moves",
    
    "internal_liquidity": {
        "definition": "Imbalances INSIDE the current range (between recent swing high/low)",
        "types": ["fvg_zones", "order_blocks", "equal_highs_inside_range", "equal_lows_inside_range"],
        "trading_priority": "1st target — price typically reaches internal liquidity FIRST before external",
        "mechanics": "Price sweeps internal liquidity, reverses, then hunts external liquidity for TP",
    },
    
    "external_liquidity": {
        "definition": "Liquidity OUTSIDE the current range (swing highs/lows, PDH/PDL, equal extremes beyond range)",
        
        "sources": {
            "swing_highs_lows": "Previous market structure extremes — where retail SLs cluster",
            "pdh_pdl": {
                "pdh": "Previous Day High — primary external liquidity target for bullish moves",
                "pdl": "Previous Day Low — primary external liquidity target for bearish moves",
                "standard_smc": "PDH, PDL, PWH (Previous Week High), PWL treated as primary external targets",
            },
            "equal_highs_lows": "Prices where market has previously reversed — retail SL clusters",
            "session_extremes": "Asian high/low, London high/low, NY high/low — key liquidity zones",
            "gap_zones": "Opening gaps (especially over weekends) — price often revisits",
        },
        
        "trading_priority": "2nd target — reached AFTER internal liquidity swept and reversal confirmed",
        "tp_strategy": "Set primary TP at external liquidity target; use scale-out at internal confluences",
    },
    
    "liquidity_sweep": {
        "description": "Price raids retail stop losses at liquidity level, then reverses — key BOS trigger",
        "mechanics": {
            "step_1": "Price approaches swing high/low or liquidity zone",
            "step_2": "Sweep: wick breaks through liquidity level (often with high volume)",
            "step_3": "Candle body closes BACK inside the range (rejection of extreme)",
            "step_4": "Reversal candle forms: move away from swept liquidity = setup trigger",
        },
        "confirmation": "Wick through liquidity level, candle body closes back inside range",
        "high_probability": "Sweep indicates institutional order flow — strong reversal likely",
        "require_before_entry": True,
    },
    
    "stop_hunt_concept": {
        "definition": "Deliberate price move to trigger retail stop losses, then reversal",
        "identification": "Price wicks beyond swing/liquidity, reverses sharply",
        "trader_action": "After sweep, follow the reversal — high probability in reverse direction",
    },
    
    "liquidity_void_concept": {
        "definition": "Broad imbalance spanning multiple candles (wider than FVG)",
        "vs_fvg": "FVG = 3-candle imbalance; Void = imbalance over 4+ candles",
        "mechanics": "Price fills voids on the way to external liquidity targets",
        "application": "Use voids as secondary TP levels when primary targets are too far",
    },
}

# =============================================================================
# PREMIUM / DISCOUNT ZONES — ICT OTE (Optimal Trading Entry) Zones
# =============================================================================

PREMIUM_DISCOUNT = {
    "description": "Based on Fibonacci range of the most recent impulse swing (NOT static range)",
    
    "range_anchor": {
        "critical_rule": "Must be redrawn after EVERY BOS — reference always the most recent confirmed impulse leg",
        
        "bullish_structure": {
            "range_basis": "From impulse LOW to impulse HIGH (recent upward move)",
            "fib_start": "Low of impulse (0%)",
            "fib_end": "High of impulse (100%)",
        },
        
        "bearish_structure": {
            "range_basis": "From impulse HIGH to impulse LOW (recent downward move)",
            "fib_start": "High of impulse (0%)",
            "fib_end": "Low of impulse (100%)",
        },
    },
    
    "premium_zone": {
        "definition": "Above 50% of the range (upper half)",
        "trader_action": "Look for SHORTS in premium (overbought)",
        "entry_preference": "Enter shorts at upper OTE zone (0.62-0.79 fib level)",
    },
    
    "discount_zone": {
        "definition": "Below 50% of the range (lower half)",
        "trader_action": "Look for LONGS in discount (oversold)",
        "entry_preference": "Enter longs at lower OTE zone (0.62-0.79 fib level)",
    },
    
    "ote_optimal_trading_entry": {
        "range_standard_ict": (0.62, 0.79),
        "range_precision_reason": "0.62 = more aggressive; 0.79 = more conservative; DO NOT use 0.786",
        
        "sweet_spot": {
            "level": 0.705,
            "description": "Midpoint between 0.62 and 0.79 — HIGHEST probability entry level",
            "why_midpoint": "Balances aggressive entries (0.62) with pullback entries (0.79)",
            "action": "Prioritize entries at or near 0.705 within the OTE zone",
        },
        
        "lower_bound": {
            "level": 0.62,
            "description": "Aggressive entry — immediate after first reversal signal",
            "use_case": "When price is near bottom of OTE but reversal confirmation is strong",
        },
        
        "upper_bound": {
            "level": 0.79,
            "description": "Conservative entry — requires more pullback confirmation",
            "use_case": "When you want deeper pullback before entry; lower risk but later entry",
        },
    },
    
    "invalidation_at_50_percent": {
        "rule": "If price breaks through 50% (midpoint), OTE zone is invalidated",
        "meaning": "New range likely forming — redraw Fibonacci from new impulse leg",
    },
}

# =============================================================================
# SESSIONS (Updated with WAT timezone — UTC+1)
# =============================================================================
SESSIONS = {
    "london": {
        "open_utc": "07:00",
        "open_wat": "08:00",
        "close_utc": "16:00",
        "close_wat": "17:00",
        "trade": True,
        "description": "London session - highest liquidity for EUR pairs",
    },
    
    "new_york": {
        "open_utc": "13:00",
        "open_wat": "14:00",
        "close_utc": "21:00",
        "close_wat": "22:00",
        "trade": True,
        "description": "New York session - highest liquidity for USD pairs",
    },
    
    "asian": {
        "open_utc": "00:00",
        "open_wat": "01:00",
        "close_utc": "09:00",
        "close_wat": "10:00",
        "trade": False,
        "description": "Asian session - lower liquidity, used for setup hunting",
    },
    
    "killzones": {
        "description": "Best trading windows with confirmed price structure",
        
        "london_open_kz": {
            "name": "London Open Killzone",
            "start_utc": "07:00",
            "start_wat": "08:00",
            "end_utc": "09:00",
            "end_wat": "10:00",
            "reason": "London market opens, highest volatility for EUR pairs",
            "trade": True,
        },
        
        "newyork_open_kz": {
            "name": "New York Open Killzone (London/NY Overlap)",
            "start_utc": "13:00",
            "start_wat": "14:00",
            "end_utc": "15:00",
            "end_wat": "16:00",
            "reason": "NY market opens + London/NY overlap, extreme liquidity & structure",
            "trade": True,
        },
        
        "london_close_kz": {
            "name": "London Close Killzone",
            "start_utc": "15:00",
            "start_wat": "16:00",
            "end_utc": "16:00",
            "end_wat": "17:00",
            "reason": "London session closes, final setup opportunities",
            "trade": True,
        },
    },
    
    "avoid_zones": {
        "reason": "Times to AVOID due to low liquidity or whipsaw risk",
        
        "first_15_min_opens": {
            "description": "First 15 minutes of major session opens",
            "reason": "Low structure clarity, high slippage, whipsaws",
            "action": "SKIP trading entirely during these windows",
        },
        
        "between_sessions": {
            "description": "Dead zones between major sessions (when only one market open)",
            "reason": "Low volume, unpredictable moves, wide spreads",
            "action": "Only trade if exceptional setup confirmed",
        },
    },
}

# =============================================================================
# ENTRY EXECUTION MAPPING (Explicit Timeframe Rules)
# =============================================================================
ENTRY_EXECUTION_MAPPING = {
    "description": "Confirm bias on one timeframe, execute on lower timeframe",
    
    "standard_mapping": {
        "bias_timeframe": "H4",
        "entry_timeframes": "M15",
        "rule": "Check 4H for direction bias, but pull trigger on 15M",
        "critical_rule": "Never enter on 4H directly — use 15M/1H for precision timing",
    },
}

# =============================================================================
# ENTRY RULES (UPDATED: BOS + Liquidity Sweep Primary Trigger)
# =============================================================================
ENTRY_RULES = {
    "bias_required": True,
    "bias_timeframe": ["H4"],                        # 4H trend bias is the governing context
    "setup_timeframe": ["H1", "M30"],              # 1H/30m setup zone where FRVP + OB confluence is evaluated
    "entry_timeframe": ["M15", "M5", "M1"],       # Sniper entry timeframes on the same TF as the target OB

    "primary_trigger": "bos_with_liquidity_sweep_or_frvp_retest",

    "primary_trigger_definition": {
        "description": "Break of Structure (BOS) confirmed by liquidity sweep and/or FRVP retest at a valid level",
        "components": [
            "Price breaks and closes beyond the most recent swing high or low",
            "Liquidity sweep may occur before or alongside the break at the swing point",
            "POC/VAH/VAL retest must be confirmed by the 5-candle rule before entry",
        ],
        "confirmation": "Candle close beyond the swing point or level, with retest confirmation when the level is targeted",
    },

    "secondary_trigger": "CHoCH_with_retracement_to_fvg_or_ifvg",
    "secondary_trigger_definition": {
        "description": "Change of Character (CHoCH) with retracement to FVG or inverted FVG (iFVG)",
        "components": [
            "First structural break against prevailing trend (CHoCH)",
            "Price retraces to nearby FVG or iFVG on entry timeframe",
            "Reversal candle forms at FVG/iFVG confirming entry",
            "liquidity sweep may occur at FVG/iFVG, further confirming institutional interest",
        ],
        "confirmation": "Reversal candle at FVG/iFVG with supportive price action",
    },

    "tertiary_trigger": "retest_of_broken_structure_with_confluence",
    "tertiary_trigger_definition": {
        "description": "Retest of broken structure with confluence",
        "components": [
            "Price retests previously broken structure",
            "Confluence of multiple factors (e.g., support/resistance, volume, sentiment)",
        ],
        "confirmation": "Candle close beyond broken structure with supportive price action",
    },

    "second_tertiary_trigger": "order_block_retest_with_confluence",
    "second_tertiary_trigger_definition": {
        "description": "Order block retest with confluence",
        "components": [
            "Order block forms on entry timeframe",
            "Price retests the order block level",
            "Confluence of multiple factors (e.g., support/resistance, volume, sentiment)",
        ],
        "confirmation": "Candle close beyond order block with supportive price action",
    },

    "number_of_triggers_required": 1,  # Only one of the primary or secondary triggers is required for entry

    "no_counter_trend": True,
    "counter_trend_rule": "Do NOT enter shorts if 4H bias is bullish; do NOT enter longs if 4H bias is bearish",
    
    "confluence_factors": [
        "price_at_swing_point",
        "liquidity_sweep_confirmed",
        "bos_confirmed_on_entry_tf",
        "bias_direction_alignment",
    ],
    
    "minimum_confluences": 3,  # BOS + sweep + bias required (all 3 mandatory)
}

# -----------------------------------------------------------------------------
# RISK MANAGEMENT
# -----------------------------------------------------------------------------
# !! CRITICAL: Fill this in accurately — this directly controls money

RISK_MANAGEMENT = {
    # === ACCOUNT RISK LIMITS ===
    "risk_per_trade_percent": 3.0,      # Hard maximum loss budget per trade
    "max_single_trade_risk_percent": 3.0,
    "max_daily_risk_percent": 10.0,     # Stop entries when UTC daily loss reaches 10%
    "max_open_trades": 2,               # Maximum 2 concurrent positions
    "total_risk_per_max_open_trades": 6.0, # Two concurrent positions may risk at most 3% each
    "max_single_trade_lots": 10.0,
    "min_single_trade_lots": 0.01,
    "max_trades_per_day": 10,           # Hard daily trade limit

    # === CONSECUTIVE LOSS TRACKING & CIRCUIT BREAKER ===
    "consecutive_loss_tracking": {
        "enabled": True,
        "consecutive_losses_threshold": 2,
        "action_on_threshold": "stop_trading_for_rest_of_day",
        "reduction_action": {
            "reduce_risk_to_percent": 3.0,
            "apply_for_next_n_trades": 0,
        },
    },
    
    # === STOP LOSS ===
    "stop_loss": {
        "placement": "swing_point_based",  # Place SL beyond recent swing extreme
        
        "swing_point_rule": {
            "for_longs": "Just beyond most recent swing low",
            "for_shorts": "Just beyond most recent swing high",
            "lookback_candles": 10,         # Scan last 10 candles for swing
            "definition": "Lowest low (longs) or highest high (shorts) in lookback period",
        },
        
        "pip_range": {
            "min_pips": 10,
            "max_pips": 30,
            "tight_structure_guidance": "10-15 pips (clean/tight swings)",
            "volatile_market_guidance": "20-30 pips (elevated volatility or wider swings)",
        },
        
        "structure_integrity_rule": {
            "never_place_in_middle": True,
            "description": "SL must be at logical structural level (swing extreme or OB), NEVER between structure points",
            "enforcement": "Reject trade if nearest swing is unreasonably far away",
        },
    },
    
    # === LOT SIZING FORMULA ===
    "lot_sizing": {
        "method": "formula_based",
        
        "formula_description": "Lot Size = Risk budget / broker-calculated loss per lot at the structural stop",
        
        "calculation_steps": {
            "step_1": "Risk budget = account balance × up to 3%",
            "step_2": "Use broker-calculated one-lot loss at the structural stop plus slippage allowance",
            "step_3": "Floor the volume to the broker volume step and cap at 10 lots",
            "step_4": "Reject if minimum volume exceeds the risk budget or available margin",
        },
        
        "example": {
            "account": "$10,000",
            "risk_percent": "3% maximum",
            "risk_amount": "no more than 3% of current account balance",
            "sl_distance": "Use actual instrument stop distance",
            "Pip_value": "Use broker tick-value and contract specifications",
            "result": "Broker-sized position rounded down to its volume step and capped at 10 lots",
        },
        
        "multi_position_allocation": {
            "rule": "When entering 2 positions together, each is capped at 3%; aggregate open risk is capped at 6%",
            "example": "On a $10,000 balance, each position risks at most $300 and is sized against its own stop",
            "aggregate_limit": "Both positions combined must NOT exceed 6% account risk",
        },
    },
    
    # === TAKE PROFIT (STRUCTURE + R:R GUARDRAILS) ===
    "take_profit": {
        "method": "next_valid_ob_on_same_entry_tf_with_rr_guardrails",

        "logic_flow": [
            "1. Identify the next valid order block on the same sniper-entry timeframe (M15/M5/M1)",
            "2. Select a valid structural target between 1:1 and 1:10 R:R from the swing-point SL",
            "3. Retarget upward/downward if the target OB becomes active→breaker or breaker→removed while the trade is open",
        ],

        "rr_guardrails": {
            "minimum_rr": 1.0,
            "maximum_rr": 10.0,

            "decision_logic": [
                "Accept targets only when R:R is between 1:1 and 1:10 inclusive",
                "Keep the structural stop; size the position so planned loss does not exceed 3% of balance",
                "If no valid structural target falls within the permitted R:R range: SKIP TRADE",
                "IF target OB flips active→breaker: cascade to the next valid OB on that same TF",
                "IF target OB flips breaker→removed: move SL to breakeven and let the trade ride to the next valid target",
            ],
        },
        
        "scale_out_logic": {
            "enabled": True,
            "at_first_tp_hit": "Close 50% of position, move SL to breakeven for remaining 50%",
            "remaining_action": "Let remaining 50% trail to next structural level or max R:R",
        },
    },
}

# =============================================================================
# TRADE FILTERS (UPDATED: Session Opens, BOS Retest Timeout, Post-SL Cooldown)
# =============================================================================
FILTERS = {
    # === RISK GUARDRAILS ===
    "min_rr_to_take_trade": 1.0,
    "max_rr_to_take_trade": 10.0,
    "maximum_slippage_points": 20,
    "maximum_spread_points": {"GOLD#": 30},
    "default_spread_points": {"GOLD#": 24},
    "backtest_slippage_points_per_fill": 1.0,
    "commission_per_lot_per_side": {"GOLD#": 0.0},
    
    # === SESSION FILTERING ===
    "avoid_session_opens_first_minutes": {
        "enabled": True,
        "london_open_utc": ("07:00", "07:15"),      # Avoid first 15 min of London open
        "newyork_open_utc": ("12:00", "12:15"),     # Avoid first 15 min of NY open
        "reason": "Low structure clarity at major session opens; avoid whipsaws",
    },
    
    # === SETUP INVALIDATION (BOS RETEST TIMEOUT) ===
    "bos_retest_timeout": {
        "enabled": True,
        "description": "If price does not retest mitigation block/swing within X candles post-BOS, invalidate setup",
        "timeout_candles": 10,           # Measured on entry timeframe (M15/M5/M1)
        "reason": "Retest must confirm validity of BOS; no retest = fake breakout",
    },
    
    # === POST-LOSS COOLDOWN ===
    "post_stop_loss_cooldown": {
        "enabled": True,
        "description": "After SL hit, wait 2 full candles on entry timeframe before considering re-entry",
        "cooldown_candles": 2,
        "reason": "Avoid emotional revenge trading immediately after SL",
    },
    
    # === NEWS EVENTS ===
    "avoid_news_minutes_before": 30,
    "avoid_news_minutes_after": 15,
    "high_impact_only": True,
    
    # === WEEKEND/SESSION RISK ===
    "avoid_friday_after": "18:00",       # UTC time — no weekend risk holding
    "avoid_sunday_before": "21:00",      # UTC time — thin Sunday open
    
    # === SPREAD LIMITS ===
    "spread_max_pips": {
        "EURUSD": 1.5,
        "GBPUSD": 2.0,
        "AUDUSD": 2.0,
        "USDJPY": 2.0,
        "USDCAD": 2.0,
        "USDCHF": 2.0,
        "NZDUSD": 2.5,
        "EURGBP#": 2.5,
        "EURJPY#": 3.0,
        "GBPJPY#": 3.0,
        "GOLD#": 30,
        "BTCUSD#": 50,
    }
}

# =============================================================================
# POSITION MANAGEMENT (NEW: Multi-Position Entry Rules)
# =============================================================================
POSITION_MANAGEMENT = {
    "max_concurrent_positions": 2,

    "multi_position_entry_rule": {
        "description": "Both positions entered TOGETHER after confirmed BOS + retest, NOT scaled in sequentially",

        "entry_mechanics": [
            "1. Setup confirmed: price breaks and retests swing point (BOS verified)",
            "2. Both positions sized TOGETHER based on available risk budget",
            "3. Entry candle: same candle or immediate next candle on entry timeframe (M15/M5/M1)",
            "4. Position 1 & 2: enter simultaneously or within 1-2 candles of each other",
            "5. Shared SL: both positions use same stop loss level (most recent swing extreme)",
        ],

        "position_sizing_together": {
            "total_risk_available": 6.0,
            "split_across_positions": "Each position is independently capped at 3%; combined open risk is capped at 6%",
            "example": {
                "account": "$10,000",
                "total_risk_budget": "$600 (6%)",
                "position_1_risk": "$300 (3%)",
                "position_2_risk": "$300 (3%)",
                "if_sl_20_pips": "Size each position independently using its actual stop distance and broker contract",
            },
        },

        "stop_loss_management": {
            "both_positions_share_sl": True,
            "sl_location": "Most recent swing extreme (swing high for shorts, swing low for longs)",
            "aggregate_risk_check": "Combined open SL exposure must not exceed 6% account risk",
        },
    },

    "consecutive_loss_rules": {
        "after_2_consecutive_losses": {
            "action_1": "Stop trading for the rest of the day",
            "action_2_alternative": "No reduction-of-risk schedule is used; each entry remains capped at 3%",
            "example": "Normal: up to 3% risk per entry. After 2 losses: no further trades until the next day",
            "duration": "Apply for the remainder of the current trading day",
        },
    },
}

# =============================================================================
# TRADE HISTORY TRACKING (NEW: Loss Tracking & Analytics)
# =============================================================================
TRADE_HISTORY = {
    "enabled": True,
    "tracking_enabled": True,
    
    "fields_tracked": {
        "trade_id": "Unique trade identifier (auto-generated)",
        "entry_time": "Time of entry (UTC)",
        "symbol": "Trading pair (e.g., EURUSD)",
        "side": "Long or Short",
        "entry_price": "Price at entry",
        "stop_loss": "Stop loss level (pips)",
        "take_profit": "Take profit level (pips)",
        "entry_reason": "Signal type (BOS, CHoCH, OB, etc.)",
        "lot_size": "Position size in lots",
        "risk_amount_usd": "Dollar amount risked",
        "exit_time": "Time of exit (UTC)",
        "exit_price": "Price at exit",
        "exit_reason": "Why trade closed (SL, TP, manual, etc.)",
        "pnl_usd": "Profit/loss in dollars",
        "pnl_percent": "Profit/loss as % of account",
        "rr_achieved": "Actual risk/reward ratio achieved",
        "win_loss": "Win or Loss",
    },
    
    "analytics_calculated": {
        "consecutive_wins": "Current streak of winning trades",
        "consecutive_losses": "Current streak of losing trades (triggers the daily trading halt)",
        "total_trades_today": "Number of trades in current day",
        "daily_pnl": "Cumulative P&L for the day",
        "daily_win_rate": "% of winning trades today",
        "account_balance_current": "Live account balance after each trade",
        "remaining_daily_risk": "Max additional risk available for day",
    },
    
    "position_reduction_trigger": {
        "event": "2 consecutive losses detected",
        "action": "Reduce position size by 50% for next trade (or sit out 1 hour)",
        "stored_as": "consecutive_losses_counter",
        "reset_when": "1 winning trade OR at start of new day",
    },
    
    "storage_format": "CSV file in logs/ directory, time-stamped",
    "log_file_pattern": "trade_history_YYYY-MM-DD.csv",
}

# =============================================================================
# SYSTEM PROMPT CONTEXT (Fed to Copilot/Claude via MCP)
# =============================================================================
STRATEGY_SYSTEM_PROMPT = f"""
╔═══════════════════════════════════════════════════════════════════════════╗
║  GOLD SMC + FRVP MASTER STRATEGY — INSTITUTIONAL STRUCTURE-BASED TRADING ║
║  Source of truth: gold_smc_frvp_master_strategy.md                        ║
╚═══════════════════════════════════════════════════════════════════════════╝

You are an advanced AI trading assistant for the Gold (XAU/USD) SMC + FRVP master strategy.
Your role is to establish 4H bias, locate high-probability setup zones on H1/M30, and only execute on the M15/M5/M1 sniper entry timeframe when the master strategy rules are met.

═══════════════════════════════════════════════════════════════════════════════
SECTION 1: TIMEFRAME HIERARCHY & ANALYSIS FLOW
═══════════════════════════════════════════════════════════════════════════════

TIMEFRAME MAPPING:
├─ BIAS TIMEFRAME: {TIMEFRAMES['bias']} — establish the overall 4H market bias
├─ SETUP ZONE: {TIMEFRAMES['structure']} / {TIMEFRAMES['setup']} — locate FRVP + OB confluence
├─ ENTRY TIMEFRAME: {TIMEFRAMES['entry']} — execute the sniper entry on the same TF as the target OB
└─ CONFIRMATION: {TIMEFRAMES['confirm']} — micro-structure validation and trigger confirmation

ANALYSIS FLOW (TOP-DOWN):
1. Identify directional bias on {TIMEFRAMES['bias']} (4H trend bias)
2. Evaluate structure and FRVP confluence on {TIMEFRAMES['structure']} and {TIMEFRAMES['setup']}
3. Only enter on {TIMEFRAMES['entry']} if the level has passed the 5-candle confirmation rule
4. Use {TIMEFRAMES['confirm']} for execution confirmation and quick validation

CRITICAL RULE: Never move a structural stop to manufacture a target ratio. Cap planned loss at 3% by sizing; accept only structural targets from 1:1 through 1:10 R:R; stop new entries at 10% daily loss.

═══════════════════════════════════════════════════════════════════════════════
SECTION 2: MARKET STRUCTURE CONCEPTS (SMC Standard)
═══════════════════════════════════════════════════════════════════════════════

A) BREAK OF STRUCTURE (BOS) — Primary Continuation Signal
   ├─ Definition: Price breaks & CLOSES beyond most recent swing high (shorts) or swing low (longs)
   ├─ DYNAMIC SWING MINIMUMS (instrument-specific, NOT fixed):
   │  ├─ EURUSD, GBPUSD, USDJPY: 15-20 pips minimum
   │  ├─ EURGBP, EURJPY: 25-35 pips minimum
   │  ├─ GBPJPY, crosses: 30-50 pips minimum
   │  ├─ GOLD#: 150-300 pips minimum
   │  └─ BTCUSD#: 500-1000 pips minimum
   ├─ FVG DISPLACEMENT REQUIREMENT (CRITICAL):
   │  ├─ BOS must leave a Fair Value Gap (3-candle imbalance) to confirm institutional move
   │  ├─ If BOS has NO FVG → likely false break or retail-driven move (LOWER PROBABILITY)
   │  └─ Validate: scan impulse candles for 3-candle imbalance after BOS
   ├─ Confirmation: Candle CLOSE beyond swing point (not just wick touch)
   └─ Age Rule: OB/setup valid within 10 candles post-BOS; no retest = invalidate

B) CHANGE OF CHARACTER (CHoCH) — Reversal Signal
   ├─ Definition: First structural break AGAINST prevailing trend
   ├─ Bullish structure: break of lower high = first reversal sign
   ├─ Bearish structure: break of higher low = first reversal sign
   ├─ Requires liquidity sweep confirmation
   └─ Often leads to strong directional move

C) SWING IDENTIFICATION
   ├─ Swing High: Candle with highest high ±{MARKET_STRUCTURE['swing_identification']['lookback_candles']} candles left/right
   ├─ Swing Low: Candle with lowest low ±{MARKET_STRUCTURE['swing_identification']['lookback_candles']} candles left/right
   ├─ Confirmation: After 5+ candles past potential swing, if no new extreme = confirmed
   └─ Filter: Only trade swings meeting minimum size (dynamic per instrument)

═══════════════════════════════════════════════════════════════════════════════
SECTION 3: ORDER BLOCKS (OB) — Institutional Accumulation/Distribution Zones
═══════════════════════════════════════════════════════════════════════════════

DEFINITION: Last candle before a strong impulsive move that causes BOS

TWO DRAWING METHODS:
├─ Method 1: BODY-ONLY (preferred for clean structures)
│  ├─ Bullish OB: Open to Close of trigger candle = buy zone
│  ├─ Bearish OB: Close to Open of trigger candle = sell zone
│  └─ Use when: tight structures, body clearly defined
│
└─ Method 2: WICK-INCLUSIVE (use when wick >2x body size)
   ├─ Bullish OB: Low to High of trigger candle = buy zone
   ├─ Bearish OB: High to Low of trigger candle = sell zone
   └─ Use when: long wicks indicate true institutional zone

INVALIDATION & MITIGATION:
├─ MITIGATED: Price touches OB and reverses = OB still valid, high probability
├─ INVALIDATED: Price candle CLOSES beyond OB boundary = OB broken
└─ BREAKER BLOCK (High Probability):
   ├─ When OB is invalidated + liquidity swept, it FLIPS POLARITY
   ├─ Bullish OB → invalidated → becomes bearish breaker block
   ├─ Re-entries at breaker block = high-probability reversal entries
   └─ Often leads to strong opposite-direction moves

CONFLUENCE RULES:
├─ OB + FVG overlap in impulse direction = MAXIMUM confluence
└─ OB + retest + rejection = HIGHEST probability entry

═══════════════════════════════════════════════════════════════════════════════
SECTION 4: FAIR VALUE GAPS (FVG) & INVERTED FVGs (iFVG) — Imbalances
═══════════════════════════════════════════════════════════════════════════════

DEFINITION: 3-candle pattern where C1 high & C3 low don't overlap (bullish)
           or C1 low & C3 high don't overlap (bearish)

DYNAMIC MINIMUM SIZES (instrument-specific):
├─ EURUSD, GBPUSD, USDJPY: 5-10 pips
├─ EURGBP, EURJPY: 10-15 pips
├─ GBPJPY: 15-25 pips
├─ GOLD#: 50-100 pips
└─ BTCUSD#: 200-500 pips

INVALIDATION LEVELS (NOT BINARY):
├─ LEVEL 1 — WEAKENED:
│  ├─ Trigger: Price closes beyond 50% (CE = Common Equalizer) with no reversal
│  ├─ Status: FVG weakened but still valid (lower probability)
│  └─ Action: Can still trade, but expect less reliable reversal
│
└─ LEVEL 2 — FULLY INVALID:
   ├─ Trigger: Price candle CLOSES beyond FAR BOUNDARY (opposite side)
   ├─ Status: FVG fully invalidated, zone broken
   └─ Action: DISCARD FVG, do not use as entry or TP

FVG VALIDATION RULE (Cross-Timeframe Confirmation):
├─ Validate FVG on 4x LOWER timeframe than identified
├─ Example: H4 FVG → confirm on H1; H1 FVG → confirm on M15
├─ If lower TF shows clean fill with NO reversal = FALSE FVG (reject entry)
└─ If lower TF shows rejection at FVG = CONFIRMED institutional zone

INVERTED FVG (iFVG) — High-Probability Reversal:
├─ When FVG is fully invalidated, zone FLIPS POLARITY
├─ Bullish FVG (imbalance above) → invalidated → Bearish iFVG (imbalance below)
├─ Bearish FVG (imbalance below) → invalidated → Bullish iFVG (imbalance above)
├─ iFVGs trigger STRONG reversals in opposite direction
└─ HIGHEST PROBABILITY: combine iFVG + BOS + liquidity sweep

ENTRY STRATEGY:
├─ Entry at FVG 50% (CE = Common Equalizer midpoint)
├─ Scale into zone from upper boundary toward 50%
├─ Prioritize FVGs nested INSIDE Order Blocks
└─ Use iFVGs as high-probability reversal entry triggers

═══════════════════════════════════════════════════════════════════════════════
SECTION 5: LIQUIDITY CONCEPTS — Internal vs External (Smart Money Targeting)
═══════════════════════════════════════════════════════════════════════════════

LIQUIDITY STRATEGY: Smart Money hunts retail stop losses BEFORE institutional moves

INTERNAL LIQUIDITY (1st Target):
├─ Definition: Imbalances INSIDE current range (swing high to swing low)
├─ Types: FVGs, Order Blocks, equal highs/lows inside range
├─ Trading Logic: Price reaches internal liquidity FIRST, reverses, then hunts external
├─ Mechanics: Sweep → Reverse → Hunt external
└─ Strategy: Take 50% profit at internal, trail remaining to external

EXTERNAL LIQUIDITY (2nd Target):
├─ Definition: Liquidity OUTSIDE current range
├─ SOURCES (in priority order):
│  ├─ PDH/PDL (Previous Day High/Low) — PRIMARY external targets
│  ├─ PWH/PWL (Previous Week High/Low)
│  ├─ Swing extremes from previous structures
│  ├─ Equal highs/lows beyond current range
│  ├─ Session extremes (Asian/London/NY high/low)
│  └─ Gap zones (especially weekend gaps)
└─ Strategy: Set primary TP at external liquidity target; trail after 50% partial

LIQUIDITY SWEEP — Key BOS Confirmation:
├─ Step 1: Price approaches swing high/low or liquidity zone
├─ Step 2: Sweep — wick BREAKS through liquidity (often high volume)
├─ Step 3: Body rejects — candle closes BACK inside range
├─ Step 4: Reversal — move away from swept liquidity = ENTRY SIGNAL
├─ Confirmation: Wick through + body rejection = institutional order flow
└─ High Probability: Sweep indicates Smart Money accumulation/distribution

STOP HUNT & LIQUIDITY VOID:
├─ Stop Hunt: Deliberate wicks to trigger SLs, then reversal (follow the reversal)
├─ Liquidity Void: Broad imbalance (4+ candles) vs FVG (3 candles)
├─ Void Strategy: Use as secondary TP when primary is too far
└─ Mechanics: Price fills voids on way to external liquidity targets

═══════════════════════════════════════════════════════════════════════════════
SECTION 6: PREMIUM/DISCOUNT ZONES — ICT OTE (Optimal Trading Entry)
═══════════════════════════════════════════════════════════════════════════════

FIBONACCI ANCHOR (CRITICAL — Dynamic, Not Static):
├─ REDRAW after EVERY BOS — reference most recent CONFIRMED impulse leg
├─ Bullish structure: Fib from impulse LOW (0%) to impulse HIGH (100%)
├─ Bearish structure: Fib from impulse HIGH (0%) to impulse LOW (100%)
├─ If price breaks 50% midpoint: OTE invalidated, create new Fibonacci
└─ REASON: Trading institutional impulses, not static levels

OTE OPTIMAL TRADING ENTRY ZONES:
├─ Standard ICT Range: 0.62 to 0.79 (NOT 0.618-0.786)
├─ 0.62 boundary: Aggressive entry (immediate post-reversal signal)
├─ 0.79 boundary: Conservative entry (requires more pullback)
│
└─ SWEET SPOT: 0.705 (Midpoint)
   ├─ HIGHEST probability entry level (balances aggressive & conservative)
   ├─ Between 0.62 (aggressive) and 0.79 (conservative)
   ├─ Prioritize entries at or near 0.705
   └─ Use 0.62 for strong confirmation, 0.79 for deeper pullback setups

PREMIUM ZONE (Above 50% — Look for SHORTS):
├─ Enter shorts at upper OTE (0.62-0.79) in discount
├─ Price overbought relative to impulse
└─ Expect reversal downward

DISCOUNT ZONE (Below 50% — Look for LONGS):
├─ Enter longs at lower OTE (0.62-0.79) in discount
├─ Price oversold relative to impulse
└─ Expect reversal upward

═══════════════════════════════════════════════════════════════════════════════
SECTION 7: ENTRY TRIGGERS (Multiple Routes to Entry)
═══════════════════════════════════════════════════════════════════════════════

ONLY ONE TRIGGER REQUIRED — But all must align with bias

PRIMARY TRIGGER: BOS + LIQUIDITY SWEEP
├─ Bias: Confirmed on {TIMEFRAMES['bias']}
├─ Setup: Swing high/low identified
├─ Sweep: Wick breaks liquidity, body rejects back inside
├─ BOS: Candle closes beyond swing point on {TIMEFRAMES['entry']}
├─ Entry: On BOS confirmation candle
└─ Probability: HIGHEST

SECONDARY TRIGGER: CHoCH + FVG/iFVG Retracement
├─ Setup: First structural break against trend (CHoCH)
├─ Retracement: Price retraces to nearby FVG or iFVG
├─ Reversal: Entry candle forms at FVG/iFVG
├─ Sweep: Liquidity sweep at FVG adds confluence
└─ Probability: HIGH

TERTIARY TRIGGER: OB Retest + Confluence
├─ Setup: Order Block on entry timeframe
├─ Retest: Price retests OB level
├─ Confluence: Multiple factors align (support/resistance, structure, volume)
├─ Entry: Candle close beyond OB with supportive action
└─ Probability: MEDIUM-HIGH

COUNTER-TREND FILTER:
├─ NEVER enter shorts if {TIMEFRAMES['bias']} bias is BULLISH
├─ NEVER enter longs if {TIMEFRAMES['bias']} bias is BEARISH
├─ Bias alignment is MANDATORY for all entries
└─ Exception: CHoCH can be reversal, but must have strong confluence

═══════════════════════════════════════════════════════════════════════════════
SECTION 8: RISK MANAGEMENT & POSITION SIZING
═══════════════════════════════════════════════════════════════════════════════

ACCOUNT RISK LIMITS:
├─ Risk per trade: 3.0% maximum ($300 on $10k account)
├─ Max concurrent positions: 2
├─ Combined open risk (both positions): 6.0% maximum
├─ Max daily realized loss: 10.0% of UTC day-start balance (stop trading if hit)
├─ Max trades per day: 10 hard limit
└─ Consecutive loss tracking: ENABLED

STOP LOSS PLACEMENT:
├─ Method: Swing-point based (at logical structural level)
├─ For LONGS: Just beyond most recent swing low (10-candle lookback)
├─ For SHORTS: Just beyond most recent swing high (10-candle lookback)
├─ Keep the structural stop; do not tighten it to force R:R
├─ If stop is invalid or inside broker minimum distance: reject the setup
└─ Size the order so worst-case modeled loss, including execution allowance, is <= 3%

LOT SIZING FORMULA:
├─ Risk budget = min(requested risk, 3% of current balance)
├─ Calculate loss per lot using the broker's tick value and actual stop distance
├─ Floor volume to broker volume_step; never round up above the risk budget
├─ Permitted volume: broker minimum through min(10 lots, broker maximum)
├─ Reject if the minimum valid volume exceeds the 3% risk budget or free margin
└─ Combined open risk for two positions must not exceed 6%

POSITION MANAGEMENT:
├─ Entry Mechanics: BOTH positions entered TOGETHER, NOT sequentially
├─ Same Candle Entry: Both enter same candle or within 1-2 candles
├─ Shared SL: Both use same stop loss level (swing extreme)
├─ Scale-Out: At 1st TP hit → close 50%, move SL to BE, trail 50%
└─ No Sequential Scaling: Reject scaled-in entries

CONSECUTIVE LOSS TRACKING:
├─ Trigger: 2 consecutive losses detected
├─ Action: Stop new entries for the rest of the UTC trading day
├─ Daily loss cap: Stop new entries at 10% realized loss from day-start balance
└─ Risk per entry never exceeds 3%

═══════════════════════════════════════════════════════════════════════════════
SECTION 9: TAKE PROFIT (R:R GUARDRAILS & STRUCTURE)
═══════════════════════════════════════════════════════════════════════════════

TP STRATEGY: Identify next swing high/low on entry timeframe, validate R:R

R:R GUARDRAILS:
├─ Minimum R:R: 1.0 (1:1)
├─ Maximum R:R: 10.0 (1:10)
│
├─ Decision Logic:
│  ├─ IF structural target offers < 1:1 R:R → SKIP or evaluate the next structural target
│  ├─ IF target offers 1:1 to 1:10 R:R → SET TP AT THAT STRUCTURAL LEVEL
│  └─ IF no structural target offers up to 1:10 R:R → SKIP; never distort the stop
│
└─ Calculation: R:R = (Target - Entry) / (Entry - SL)

STRUCTURAL TP PLACEMENT:
├─ Primary: Next significant swing high/low on entry timeframe
├─ Secondary: Key support/resistance level
├─ External Liquidity: PDH/PDL, equal extremes, session highs/lows
└─ Confluence: Combine multiple levels for final TP

SCALE-OUT LOGIC:
├─ At 1st TP (1:1 R:R): Close 50% of position
├─ Move SL to Breakeven for remaining 50%
├─ Trail remaining 50%: Let run to next structural level or max R:R
└─ Purpose: Lock in profits while capturing extended moves

═══════════════════════════════════════════════════════════════════════════════
SECTION 10: TRADE FILTERS & INVALIDATION RULES
═══════════════════════════════════════════════════════════════════════════════

SESSION FILTERING:
├─ AVOID first 15 minutes of session opens (low structure clarity)
│  ├─ London open: 07:00-07:15 UTC
│  └─ New York open: 13:00-13:15 UTC
├─ KILLZONES (BEST trading windows):
│  ├─ London Open: 07:00-09:00 UTC (highest EUR volatility)
│  ├─ NY Open (London/NY Overlap): 13:00-15:00 UTC (EXTREME liquidity)
│  └─ London Close: 15:00-16:00 UTC (final setup opportunities)
└─ AVOID: Weekend risk (Friday <18:00 UTC), thin Sunday opens (>21:00 UTC)

BOS RETEST TIMEOUT (Critical Invalidation):
├─ Rule: If price does NOT retest swing within 10 candles post-BOS → INVALIDATE
├─ Measured on: Entry timeframe (M15/M5/M1)
├─ Reason: Retest confirms BOS validity; no retest = fake breakout
├─ Action: Cancel setup, wait for new signal
└─ Purpose: Filter out false breaks early

POST-SL COOLDOWN:
├─ Rule: After SL hit, wait 2 full candles before re-entry
├─ Measured on: Entry timeframe
├─ Purpose: Avoid emotional revenge trading
└─ Action: Let market stabilize before next setup

SPREAD LIMITS (Per instrument):
├─ EURUSD: 1.5 pips max
├─ GBPUSD, AUDUSD, USDJPY, USDCAD, USDCHF: 2.0 pips max
├─ NZDUSD: 2.5 pips max
├─ EURGBP, EURJPY, GBPJPY: 3.0 pips max
├─ GOLD#: 30 broker points max (0.30 price units at 0.01 point)
└─ BTCUSD#: 50 pips max

NEWS FILTERING:
├─ Avoid: ±30 minutes BEFORE high-impact news
├─ Avoid: ±15 minutes AFTER high-impact news
└─ Purpose: Prevent whipsaw from economic data

═══════════════════════════════════════════════════════════════════════════════
SECTION 11: TRADE TRACKING & ANALYTICS
═══════════════════════════════════════════════════════════════════════════════

COMPREHENSIVE TRADE LOGGING:
├─ Trade ID (auto-generated)
├─ Entry/Exit times (UTC)
├─ Symbol, side (long/short), prices
├─ Stop loss, take profit levels
├─ Entry reason (BOS, CHoCH, OB, etc.)
├─ Lot size, risk amount (USD)
├─ Exit reason (SL hit, TP hit, manual, etc.)
├─ P&L (USD & %)
├─ R:R achieved vs target
├─ Win/Loss classification
└─ Storage: CSV file in logs/ directory (trade_history_YYYY-MM-DD.csv)

ANALYTICS CALCULATED:
├─ Consecutive wins/losses (triggers position reduction at 2 losses)
├─ Daily P&L & win rate
├─ Total trades today
├─ Account balance after each trade
├─ Remaining daily risk budget
└─ Purpose: Monitor performance & enforce risk rules

═══════════════════════════════════════════════════════════════════════════════
SECTION 12: KEY TRADING RULES (DO's & DON'Ts)
═══════════════════════════════════════════════════════════════════════════════

✓ ALWAYS DO:
  ✓ Confirm bias on {TIMEFRAMES['bias']} before ANY entry
  ✓ Execute on {TIMEFRAMES['entry']}, never directly on bias timeframe
  ✓ Require liquidity sweep confirmation for BOS
  ✓ Validate FVGs on 4x lower timeframe before entry
  ✓ Identify institutional levels (OB, FVG, PDH/PDL, swings)
  ✓ Check R:R between 1:1 and 1:10
  ✓ Place SL at logical structural level (swing extreme or OB)
  ✓ Cap each trade's modeled loss at 3% and total open risk at 6%
  ✓ Stop new entries at 10% UTC daily loss or after 2 consecutive losses
  ✓ Document all trades for analytics & learning

✗ NEVER DO:
  ✗ Enter counter to {TIMEFRAMES['bias']} bias
  ✗ Place SL in middle of structure (between levels)
  ✗ Take a structural target beyond 1:10 R:R
  ✗ Trade first 15 min of major session opens
  ✗ Take trade with R:R < 1:1
  ✗ Scale in sequentially (both positions together only)
  ✗ Use BOS without liquidity sweep confirmation
  ✗ Ignore FVG invalidation levels
  ✗ Trade without validating structure on lower TF
  ✗ Hold positions over weekend (close Friday <18:00 UTC)

═══════════════════════════════════════════════════════════════════════════════
TRADING INSTRUMENTS: {len(INSTRUMENTS)} Pairs
{', '.join(INSTRUMENTS)}

═══════════════════════════════════════════════════════════════════════════════
SUMMARY: You now have institutional-grade SMC framework for structure-based trading.
Use this knowledge to identify precise entry points, manage risk, and execute with confidence.
═══════════════════════════════════════════════════════════════════════════════
"""
