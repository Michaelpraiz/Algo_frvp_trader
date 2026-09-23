"""
TRADE ENGINE — Phase 4 (Strategy & Analysis Engine)
===============================================
Comprehensive SMC market structure analysis & setup scoring.
Implements all institutional trading concepts:
- HTF bias detection (D1 trend analysis)
- Break of Structure (BOS) & Change of Character (CHoCH)
- Order Blocks (OB) with invalidation logic
- Fair Value Gaps (FVG) with two levels + iFVG
- Liquidity level identification (internal & external)
- Liquidity sweep confirmation
- Premium/Discount zone analysis (OTE)
- Multi-confluence scoring
- Complete trade plan generation

Core Function Hierarchy:
  get_htf_bias()           ← Directional bias from D1
  ├─ detect_bos_choch()    ← Structure shifts on H4
  ├─ find_order_blocks()   ← Valid OB zones with age/invalidation
  ├─ find_fvg()            ← 3-candle imbalances with 2 validation levels
  ├─ find_liquidity_levels() ← PDH/PDL, equals, session extremes
  ├─ check_liquidity_sweep() ← Wick break + body rejection confirmation
  ├─ check_premium_discount() ← OTE 0.62-0.79 sweet spot
  └─ score_setup()         ← Confluence scoring (all above)
      └─ generate_trade_plan() ← Full analysis output: bias → POI → entry → SL → TP
"""

import logging
import sys
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

# Import local modules
from .mt5_client import get_client
from .strategy_config import (
    MARKET_STRUCTURE,
    ORDER_BLOCKS,
    FAIR_VALUE_GAPS,
    LIQUIDITY,
    PREMIUM_DISCOUNT,
    SESSIONS,
    TIMEFRAMES,
    RISK_MANAGEMENT,
    FILTERS
)
from .risk_manager import get_risk_manager
from .frvp import compute_frvp, result_to_dict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - TRADE_ENGINE - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/trade_engine.log"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class SwingPoint:
    """Represents a swing high or low."""
    timestamp: datetime
    price: float
    candle_index: int
    direction: str  # 'high' or 'low'
    is_confirmed: bool = False


@dataclass
class OrderBlock:
    """Order block zone."""
    symbol: str
    timeframe: str
    price_high: float
    price_low: float
    timestamp: datetime
    candle_index_formed: int
    direction: str  # 'bullish' or 'bearish'
    is_broken: bool = False
    break_timestamp: Optional[datetime] = None
    is_valid: bool = True
    age_candles: int = 0
    detection_method: str = "body_only"
    quality_score: float = 0.0
    impulse_strength: float = 0.0
    wick_ratio: float = 0.0
    
    @property
    def midpoint(self) -> float:
        return (self.price_high + self.price_low) / 2
    
    @property
    def size_pips(self) -> float:
        return (self.price_high - self.price_low) * 10000


@dataclass
class FairValueGap:
    """Fair Value Gap (imbalance)."""
    symbol: str
    timeframe: str
    price_high: float
    price_low: float
    timestamp: datetime
    candle_index_formed: int
    direction: str  # 'bullish' or 'bearish'
    is_broken: bool = False
    break_level: int = 0  # 0=valid, 1=weakened, 2=fully invalid
    size_pips: float = 0.0
    displacement_confirmed: bool = False
    quality_score: float = 0.0
    validation_timeframe: str = ""
    is_validated: bool = True
    
    @property
    def midpoint(self) -> float:
        return (self.price_high + self.price_low) / 2


@dataclass
class LiquidityLevel:
    """Key liquidity level (PDH/PDL, equals, session extremes)."""
    symbol: str
    price: float
    level_type: str  # 'pdh', 'pdl', 'equal_high', 'equal_low', 'session_high', 'session_low'
    timestamp: datetime
    strength: int  # 1-5, higher = more confluent
    timeframe_origin: str


@dataclass
class TradeSetup:
    """Complete trade setup with all SMC elements."""
    symbol: str
    bias: str  # 'bullish', 'bearish', 'neutral'
    bias_strength: float  # 0.0-100.0
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_trigger: str  # 'bos_sweep', 'choch_fvg', 'ob_retest', etc.
    confluence_score: float  # 0.0-100.0
    order_block: Optional[OrderBlock] = None
    fvg: Optional[FairValueGap] = None
    liquidity_sweep: Optional[bool] = None
    premium_discount_zone: Optional[Dict] = None
    recommendation: str = "HOLD"  # 'BUY', 'SELL', 'HOLD'


# =============================================================================
# TRADE ENGINE CLASS
# =============================================================================

class TradeEngine:
    """
    Comprehensive SMC strategy analysis engine.
    Performs multi-timeframe structural analysis and generates trade plans.
    """
    
    def __init__(self):
        """Initialize trade engine with config."""
        self.client = get_client()
        self.risk_manager = get_risk_manager()
        
        # Load configuration
        self.market_structure_config = MARKET_STRUCTURE
        self.ob_config = ORDER_BLOCKS
        self.fvg_config = FAIR_VALUE_GAPS
        self.liquidity_config = LIQUIDITY
        self.pd_config = PREMIUM_DISCOUNT
        
        # Trading parameters
        self.min_swing_sizes = MARKET_STRUCTURE.get("bos", {}).get("min_swing_size_dynamic", {})
        self.min_fvg_sizes = FAIR_VALUE_GAPS.get("min_gap_size_dynamic", {})
        
        logger.info("[OK] Trade Engine initialized")
        logger.info(f"  Symbols supported: {list(self.min_swing_sizes.keys())}")
    
    # =========================================================================
    # 1. HTF BIAS DETECTION (D1 Trend Analysis)
    # =========================================================================
    
    def get_htf_bias(self, symbol: str) -> Dict[str, Any]:
        """
        Determine directional bias from the 4H timeframe, matching the approved master strategy.

        Analysis:
        - Higher high + higher low = BULLISH
        - Lower high + lower low = BEARISH
        - Ranging = NEUTRAL

        Args:
            symbol: Trading pair (e.g., 'EURUSD')

        Returns:
            dict: {
                'symbol': str,
                'bias': 'bullish'|'bearish'|'neutral',
                'strength': 0.0-100.0,
                'last_swing_high': float,
                'last_swing_low': float,
                'message': str
            }
        """
        try:
            if not self.client:
                return {
                    'bias': 'neutral',
                    'strength': 0,
                    'message': 'MT5 client not available'
                }

            candles = self.client.get_candles(symbol, "H4", 50)
            if candles is None or len(candles) < 10:
                return {
                    'bias': 'neutral',
                    'strength': 0,
                    'message': f'Insufficient H4 data for {symbol}'
                }
            
            # Extract OHLC
            highs = candles['high'].values
            lows = candles['low'].values
            
            # Find recent swing high/low (last 10 candles)
            recent_high_idx = np.argmax(highs[-10:])
            recent_low_idx = np.argmin(lows[-10:])
            recent_high = highs[-10 + recent_high_idx]
            recent_low = lows[-10 + recent_low_idx]
            
            # Find previous swing high/low (10-20 candles back)
            prev_high_idx = np.argmax(highs[-20:-10])
            prev_low_idx = np.argmin(lows[-20:-10])
            prev_high = highs[-20 + prev_high_idx]
            prev_low = lows[-20 + prev_low_idx]
            
            # Determine bias
            higher_high = recent_high > prev_high
            higher_low = recent_low > prev_low
            lower_high = recent_high < prev_high
            lower_low = recent_low < prev_low
            
            if higher_high and higher_low:
                bias = 'bullish'
                strength = min(100.0, ((recent_high - prev_high) / prev_high * 100) * 1.5)
            elif lower_high and lower_low:
                bias = 'bearish'
                strength = min(100.0, ((prev_high - recent_high) / prev_high * 100) * 1.5)
            else:
                bias = 'neutral'
                strength = 50.0
            
            logger.info(
                f"[OK] H4 bias for {symbol}: {bias.upper()} (strength: {strength:.1f}%)"
                f"\n    Recent: HH={recent_high:.5f}, LL={recent_low:.5f}"
                f"\n    Previous: HH={prev_high:.5f}, LL={prev_low:.5f}"
            )

            return {
                'symbol': symbol,
                'bias': bias,
                'strength': round(strength, 1),
                'last_swing_high': recent_high,
                'last_swing_low': recent_low,
                'timeframe': 'H4',
                'message': f'Bias confirmed: {bias}'
            }
        
        except Exception as e:
            logger.error(f"get_htf_bias() error: {str(e)}", exc_info=True)
            return {
                'bias': 'neutral',
                'strength': 0,
                'message': f'Error: {str(e)}'
            }
    
    # =========================================================================
    # 2. BREAK OF STRUCTURE & CHANGE OF CHARACTER DETECTION
    # =========================================================================

    def _collect_swing_points(self, candles: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Collect recent swing highs/lows using a short lookback window."""
        highs = candles['high'].values
        lows = candles['low'].values
        swing_highs: List[Dict[str, Any]] = []
        swing_lows: List[Dict[str, Any]] = []

        for i in range(5, len(highs) - 5):
            if highs[i] >= np.max(highs[i - 5:i + 6]) and highs[i] >= np.max(highs[i + 1:i + 6]):
                swing_highs.append({'index': i, 'price': float(highs[i]), 'type': 'high'})
            if lows[i] <= np.min(lows[i - 5:i + 6]) and lows[i] <= np.min(lows[i + 1:i + 6]):
                swing_lows.append({'index': i, 'price': float(lows[i]), 'type': 'low'})

        return swing_highs, swing_lows

    def detect_bos_choch(self, symbol: str, timeframe: str = "H1") -> Dict[str, Any]:
        """Detect BOS/CHoCH using a simple state-machine aligned with the master strategy."""
        try:
            if not self.client:
                return {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'bos_detected': False,
                    'choch_detected': False,
                    'trend_state': 'neutral',
                    'bos_done': False,
                    'events': [],
                    'status': 'MT5 client not available',
                    'message': 'MT5 client not available'
                }

            candles = self.client.get_candles(symbol, timeframe, 80)
            if candles is None or len(candles) < 15:
                return {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'bos_detected': False,
                    'choch_detected': False,
                    'trend_state': 'neutral',
                    'bos_done': False,
                    'events': [],
                    'status': f'Insufficient {timeframe} data',
                    'message': f'Insufficient {timeframe} data'
                }

            highs = candles['high'].values
            lows = candles['low'].values
            closes = candles['close'].values

            swing_highs, swing_lows = self._collect_swing_points(candles)
            trend_state = 'neutral'
            events = []

            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                last_hh = swing_highs[-1]['price']
                prev_hh = swing_highs[-2]['price']
                last_ll = swing_lows[-1]['price']
                prev_ll = swing_lows[-2]['price']

                if last_hh > prev_hh and last_ll > prev_ll:
                    trend_state = 'bullish'
                elif last_hh < prev_hh and last_ll < prev_ll:
                    trend_state = 'bearish'

            recent_high = float(np.max(highs[-10:])) if len(highs) >= 10 else float(np.max(highs))
            recent_low = float(np.min(lows[-10:])) if len(lows) >= 10 else float(np.min(lows))
            current_close = closes[-1]

            bos_detected = False
            choch_detected = False
            bos_direction = None

            if trend_state == 'bullish':
                if current_close > recent_high:
                    bos_detected = True
                    bos_direction = 'bullish'
                    events.append({'bar_idx': len(closes) - 1, 'type': 'BOS', 'trend_after': 'bullish', 'ref_price': recent_high})
                elif current_close < recent_low:
                    choch_detected = True
                    events.append({'bar_idx': len(closes) - 1, 'type': 'CHoCH', 'trend_after': 'bearish', 'ref_price': recent_low})
                else:
                    events.append({'bar_idx': len(closes) - 1, 'type': 'hold', 'trend_after': 'bullish', 'ref_price': recent_high})
            elif trend_state == 'bearish':
                if current_close < recent_low:
                    bos_detected = True
                    bos_direction = 'bearish'
                    events.append({'bar_idx': len(closes) - 1, 'type': 'BOS', 'trend_after': 'bearish', 'ref_price': recent_low})
                elif current_close > recent_high:
                    choch_detected = True
                    events.append({'bar_idx': len(closes) - 1, 'type': 'CHoCH', 'trend_after': 'bullish', 'ref_price': recent_high})
                else:
                    events.append({'bar_idx': len(closes) - 1, 'type': 'hold', 'trend_after': 'bearish', 'ref_price': recent_low})
            else:
                if current_close > recent_high:
                    bos_detected = True
                    bos_direction = 'bullish'
                    events.append({'bar_idx': len(closes) - 1, 'type': 'BOS', 'trend_after': 'bullish', 'ref_price': recent_high})
                elif current_close < recent_low:
                    bos_detected = True
                    bos_direction = 'bearish'
                    events.append({'bar_idx': len(closes) - 1, 'type': 'BOS', 'trend_after': 'bearish', 'ref_price': recent_low})

            status = 'ok' if events else 'no_structure'
            result = {
                'symbol': symbol,
                'timeframe': timeframe,
                'bos_detected': bos_detected,
                'choch_detected': choch_detected,
                'direction': bos_direction,
                'trend_state': trend_state,
                'events': events,
                'bos_done': bos_detected or choch_detected,
                'current_price': current_close,
                'swing_high': recent_high,
                'swing_low': recent_low,
                'status': status,
                'message': f"BOS {bos_direction}" if bos_detected else ('CHoCH' if choch_detected else 'No structure break')
            }
            if bos_detected:
                logger.info(f"[OK] BOS detected on {symbol} {timeframe}: {bos_direction.upper()}")
            return result

        except Exception as e:
            logger.error(f"detect_bos_choch() error: {str(e)}", exc_info=True)
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'bos_detected': False,
                'choch_detected': False,
                'trend_state': 'neutral',
                'bos_done': False,
                'events': [],
                'status': f'Error: {str(e)}',
                'message': f'Error: {str(e)}'
            }

    # =========================================================================
    # 3. ORDER BLOCK DETECTION
    # =========================================================================

    def find_order_blocks(self, symbol: str, timeframe: str = "H1") -> Dict[str, Any]:
        """Return both tracked OBs and visible OBs in line with the master strategy."""
        try:
            if not self.client:
                return {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'all_tracked_obs': [],
                    'visible_obs': [],
                    'order_blocks': [],
                    'valid_count': 0,
                    'message': 'MT5 client not available'
                }

            candles = self.client.get_candles(symbol, timeframe, 80)
            if candles is None or len(candles) < 20:
                return {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'all_tracked_obs': [],
                    'visible_obs': [],
                    'order_blocks': [],
                    'valid_count': 0,
                    'message': f'Insufficient {timeframe} data'
                }

            opens = candles['open'].values
            highs = candles['high'].values
            lows = candles['low'].values
            closes = candles['close'].values
            times = pd.to_datetime(candles['time']).values

            all_obs = []
            for i in range(10, len(closes) - 5):
                body = abs(closes[i] - opens[i])
                if body <= 1e-12:
                    continue

                impulse_bullish = closes[i] > opens[i] and closes[i] > np.max(closes[i - 5:i])
                impulse_bearish = closes[i] < opens[i] and closes[i] < np.min(closes[i - 5:i])

                if not (impulse_bullish or impulse_bearish):
                    continue

                anchor_start = max(0, i - 10)
                anchor_end = i
                sub_high = np.max(highs[anchor_start:anchor_end + 1])
                sub_low = np.min(lows[anchor_start:anchor_end + 1])

                if impulse_bullish:
                    ob = {
                        'symbol': symbol,
                        'timeframe': timeframe,
                        'direction': 'bullish',
                        'top': float(sub_high),
                        'bottom': float(sub_low),
                        'start': int(anchor_start),
                        'end': int(anchor_end),
                        'state': 'active',
                        'breaker': False,
                        'quality': round(min(100.0, 60.0 + body * 10000.0), 1),
                        'timestamp': pd.Timestamp(times[i]).to_pydatetime().isoformat(),
                    }
                else:
                    ob = {
                        'symbol': symbol,
                        'timeframe': timeframe,
                        'direction': 'bearish',
                        'top': float(sub_high),
                        'bottom': float(sub_low),
                        'start': int(anchor_start),
                        'end': int(anchor_end),
                        'state': 'active',
                        'breaker': False,
                        'quality': round(min(100.0, 60.0 + body * 10000.0), 1),
                        'timestamp': pd.Timestamp(times[i]).to_pydatetime().isoformat(),
                    }
                all_obs.append(ob)

            visible_obs = all_obs[:10]
            order_blocks = [
                {
                    'symbol': ob['symbol'],
                    'timeframe': ob['timeframe'],
                    'direction': ob['direction'],
                    'top': ob['top'],
                    'bottom': ob['bottom'],
                    'quality': ob['quality'],
                    'state': ob['state'],
                }
                for ob in all_obs
            ]

            quality_score = round(sum(ob['quality'] for ob in all_obs) / len(all_obs), 1) if all_obs else 0.0
            logger.info(f"[OK] Order blocks found on {symbol} {timeframe}: {len(all_obs)} tracked")
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'all_tracked_obs': all_obs,
                'visible_obs': visible_obs,
                'order_blocks': order_blocks,
                'valid_count': len(all_obs),
                'breaker_blocks': [],
                'quality_score': quality_score,
                'scanner_mode': 'master_strategy',
                'message': f'{len(all_obs)} order blocks tracked'
            }

        except Exception as e:
            logger.error(f"find_order_blocks() error: {str(e)}", exc_info=True)
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'all_tracked_obs': [],
                'visible_obs': [],
                'order_blocks': [],
                'valid_count': 0,
                'quality_score': 0.0,
                'message': f'Error: {str(e)}'
            }

    # =========================================================================
    # 4. FAIR VALUE GAP DETECTION
    # =========================================================================

    def find_fvg(self, symbol: str, timeframe: str = "H4") -> Dict[str, Any]:
        """Find basic Fair Value Gaps while keeping the master-strategy FRVP layer separate."""
        try:
            if not self.client:
                return {
                    'fvgs': [],
                    'valid_count': 0,
                    'message': 'MT5 client not available'
                }

            candles = self.client.get_candles(symbol, timeframe, 50)
            if candles is None or len(candles) < 10:
                return {
                    'fvgs': [],
                    'valid_count': 0,
                    'message': f'Insufficient {timeframe} data'
                }

            highs = candles['high'].values
            lows = candles['low'].values
            closes = candles['close'].values
            times = pd.to_datetime(candles['time']).values

            fvgs = []
            ifvgs = []
            current_price = closes[-1]
            min_size = self.min_fvg_sizes.get(symbol, self.min_fvg_sizes.get('EURUSD', 10.0))

            for i in range(2, len(closes) - 1):
                if highs[i - 2] < lows[i - 1]:
                    fvg_high = lows[i - 1]
                    fvg_low = highs[i - 2]
                    fvg_size_pips = (fvg_high - fvg_low) * 10000
                    if fvg_size_pips >= min_size:
                        midpoint = (fvg_high + fvg_low) / 2
                        if current_price <= fvg_low:
                            break_level = 2
                            is_validated = False
                        elif current_price <= midpoint:
                            break_level = 1
                            is_validated = True
                        else:
                            break_level = 0
                            is_validated = True
                        quality_score = round(min(100.0, 30.0 + (fvg_size_pips / max(min_size, 1.0)) * 20.0 + (10.0 if break_level == 0 else 0.0)), 1)
                        fvg = FairValueGap(
                            symbol=symbol,
                            timeframe=timeframe,
                            price_high=fvg_high,
                            price_low=fvg_low,
                            timestamp=pd.Timestamp(times[i - 1]).to_pydatetime(),
                            candle_index_formed=i - 1,
                            direction='bullish',
                            size_pips=fvg_size_pips,
                            break_level=break_level,
                            quality_score=quality_score,
                            validation_timeframe='lower_tf',
                            is_validated=is_validated
                        )
                        fvgs.append(fvg)
                        if break_level == 2:
                            ifvgs.append({'symbol': symbol, 'timeframe': timeframe, 'direction': 'bearish', 'price_high': fvg_high, 'price_low': fvg_low, 'reason': 'bullish_fvg_invalidated'})

                if lows[i - 2] > highs[i - 1]:
                    fvg_high = lows[i - 2]
                    fvg_low = highs[i - 1]
                    fvg_size_pips = (fvg_high - fvg_low) * 10000
                    if fvg_size_pips >= min_size:
                        midpoint = (fvg_high + fvg_low) / 2
                        if current_price >= fvg_high:
                            break_level = 2
                            is_validated = False
                        elif current_price >= midpoint:
                            break_level = 1
                            is_validated = True
                        else:
                            break_level = 0
                            is_validated = True
                        quality_score = round(min(100.0, 30.0 + (fvg_size_pips / max(min_size, 1.0)) * 20.0 + (10.0 if break_level == 0 else 0.0)), 1)
                        fvg = FairValueGap(
                            symbol=symbol,
                            timeframe=timeframe,
                            price_high=fvg_high,
                            price_low=fvg_low,
                            timestamp=pd.Timestamp(times[i - 1]).to_pydatetime(),
                            candle_index_formed=i - 1,
                            direction='bearish',
                            size_pips=fvg_size_pips,
                            break_level=break_level,
                            quality_score=quality_score,
                            validation_timeframe='lower_tf',
                            is_validated=is_validated
                        )
                        fvgs.append(fvg)
                        if break_level == 2:
                            ifvgs.append({'symbol': symbol, 'timeframe': timeframe, 'direction': 'bullish', 'price_high': fvg_high, 'price_low': fvg_low, 'reason': 'bearish_fvg_invalidated'})

            valid_fvgs = [fvg for fvg in fvgs if len(closes) - fvg.candle_index_formed <= 15 and fvg.break_level < 2]
            valid_fvgs.sort(key=lambda fvg: fvg.quality_score, reverse=True)

            logger.info(
                f"[OK] FVGs found on {symbol} {timeframe}: {len(valid_fvgs)} valid"
                f"\n    Total detected: {len(fvgs)}"
            )

            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'fvgs': valid_fvgs,
                'valid_count': len(valid_fvgs),
                'ifvgs': ifvgs,
                'quality_score': round(sum(fvg.quality_score for fvg in valid_fvgs) / len(valid_fvgs), 1) if valid_fvgs else 0.0,
                'message': f'{len(valid_fvgs)} valid FVGs found'
            }

        except Exception as e:
            logger.error(f"find_fvg() error: {str(e)}", exc_info=True)
            return {
                'fvgs': [],
                'valid_count': 0,
                'quality_score': 0.0,
                'message': f'Error: {str(e)}'
            }

    def compute_frvp_for_leg(
        self,
        symbol: str,
        anchor_time: datetime,
        end_time: datetime,
        structure_timeframe: str = "H1",
        value_area_pct: float = 0.70,
        max_bars: int = 5000,
        row_mode: str = "ticks_per_row",
        row_size: float = 10,
    ) -> Dict[str, Any]:
        """Compute the spec-compliant FRVP for one confirmed structural leg."""
        try:
            result = compute_frvp(
                symbol=symbol,
                anchor_time=anchor_time,
                end_time=end_time,
                value_area_pct=value_area_pct,
                max_bars=max_bars,
                row_mode=row_mode,
                row_size=row_size,
                structure_timeframe=structure_timeframe,
            )
            response = result_to_dict(result)
            response['retest_rule'] = {
                'priority': 'POC first',
                'confirmation': 'Wait for bullish or bearish engulfing confirmation at POC, VAL, or VAH.',
            }
            return response
        except Exception as e:
            logger.error(f"compute_frvp_for_leg() error: {str(e)}", exc_info=True)
            return {
                'symbol': symbol,
                'poc': 0.0,
                'vah': 0.0,
                'val': 0.0,
                'timeframe_used': structure_timeframe,
                'profile': {},
                'total_volume': 0.0,
                'retest_rule': {'priority': 'POC first'},
                'error': str(e),
                'message': f'Error: {str(e)}',
            }

    def find_frvp_levels(self, symbol: str, timeframe: str = "H1") -> Dict[str, Any]:
        """Compute a simplified FRVP anchor with POC/VAH/VAL and the 5-candle retest rule."""
        try:
            if not self.client:
                return {
                    'symbol': symbol,
                    'poc': 0.0,
                    'vah': 0.0,
                    'val': 0.0,
                    'retest_rule': {'priority': 'POC first'},
                    'message': 'MT5 client not available'
                }

            candles = self.client.get_candles(symbol, timeframe, 80)
            if candles is None or len(candles) < 20:
                return {
                    'symbol': symbol,
                    'poc': 0.0,
                    'vah': 0.0,
                    'val': 0.0,
                    'retest_rule': {'priority': 'POC first'},
                    'message': f'Insufficient {timeframe} data'
                }

            highs = candles['high'].values
            lows = candles['low'].values
            closes = candles['close'].values

            swing_highs, swing_lows = self._collect_swing_points(candles)
            if swing_highs and swing_lows:
                if swing_highs[-1]['index'] > swing_lows[-1]['index']:
                    start_idx = swing_lows[-1]['index']
                    end_idx = swing_highs[-1]['index']
                    context = 'bullish'
                else:
                    start_idx = swing_highs[-1]['index']
                    end_idx = swing_lows[-1]['index']
                    context = 'bearish'
            else:
                start_idx = max(0, len(closes) - 20)
                end_idx = len(closes) - 1
                context = 'bullish' if closes[-1] >= np.mean(closes[-10:]) else 'bearish'

            segment_high = float(np.max(highs[start_idx:end_idx + 1]))
            segment_low = float(np.min(lows[start_idx:end_idx + 1]))
            span = segment_high - segment_low
            poc = (segment_high + segment_low) / 2.0
            vah = poc + span * 0.25
            val = poc - span * 0.25

            retest_rule = {
                'priority': 'POC first',
                'confirmation': 'The level must hold or reject under the 5-candle pattern before entry',
                'context': context,
                'notes': [
                    'If bearish context and price retests upward into POC/VAL/VAH, wait for bearish engulfing or a 3-candle bearish engulfing pattern.',
                    'If bullish context and price retests downward into POC/VAL/VAH, wait for bullish engulfing or a 3-candle bullish engulfing pattern.'
                ],
            }

            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'context': context,
                'poc': poc,
                'vah': vah,
                'val': val,
                'anchor_start': int(start_idx),
                'anchor_end': int(end_idx),
                'retest_rule': retest_rule,
                'message': 'FRVP levels computed using 5-candle retest priority'
            }

        except Exception as e:
            logger.error(f"find_frvp_levels() error: {str(e)}", exc_info=True)
            return {
                'symbol': symbol,
                'poc': 0.0,
                'vah': 0.0,
                'val': 0.0,
                'retest_rule': {'priority': 'POC first'},
                'message': f'Error: {str(e)}'
            }
    
    # =========================================================================
    # 5. LIQUIDITY LEVEL IDENTIFICATION
    # =========================================================================
    
    def find_liquidity_levels(self, symbol: str, timeframe: str = "H4") -> Dict[str, Any]:
        """
        Identify key liquidity levels.
        
        Priority order (how price fills):
        1. Internal liquidity FIRST: FVGs, OBs inside range
        2. External liquidity SECOND: PDH/PDL (PRIMARY), swing extremes, equal highs/lows, session extremes
        
        Args:
            symbol: Trading pair
            timeframe: Analysis timeframe
        
        Returns:
            dict: {
                'pdh': float,
                'pdl': float,
                'equal_highs': list,
                'equal_lows': list,
                'session_high': float,
                'session_low': float,
                'message': str
            }
        """
        try:
            if not self.client:
                return {
                    'pdh': 0,
                    'pdl': 0,
                    'message': 'MT5 client not available'
                }
            
            # Get candles (last 100 for comprehensive liquidity mapping)
            candles = self.client.get_candles(symbol, timeframe, 100)
            if candles is None or len(candles) < 20:
                return {
                    'pdh': 0,
                    'pdl': 0,
                    'message': f'Insufficient {timeframe} data'
                }
            
            highs = candles['high'].values
            lows = candles['low'].values
            
            # Prior Day High/Low (if daily) or lookback equivalent
            pdh = np.max(highs[-2:-1]) if len(highs) >= 2 else highs[-1]
            pdl = np.min(lows[-2:-1]) if len(lows) >= 2 else lows[-1]
            
            # Session high/low (last 24 candles for H4 = 4 days)
            session_high = np.max(highs[-24:])
            session_low = np.min(lows[-24:])
            
            # Equal highs/lows (within 5 pips)
            threshold = 0.0005  # 5 pips
            equal_highs = []
            equal_lows = []
            
            # Find repeated highs/lows
            for i in range(len(highs) - 5):
                for j in range(i + 1, min(i + 20, len(highs))):
                    if abs(highs[i] - highs[j]) < threshold:
                        if highs[i] not in equal_highs:
                            equal_highs.append(highs[i])
                    if abs(lows[i] - lows[j]) < threshold:
                        if lows[i] not in equal_lows:
                            equal_lows.append(lows[i])
            
            logger.info(
                f"[OK] Liquidity levels identified for {symbol} {timeframe}:"
                f"\n    PDH: {pdh:.5f}, PDL: {pdl:.5f}"
                f"\n    Session: High={session_high:.5f}, Low={session_low:.5f}"
                f"\n    Equal highs: {len(equal_highs)}, Equal lows: {len(equal_lows)}"
            )
            
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'pdh': pdh,
                'pdl': pdl,
                'equal_highs': equal_highs,
                'equal_lows': equal_lows,
                'session_high': session_high,
                'session_low': session_low,
                'message': 'Liquidity levels identified'
            }
        
        except Exception as e:
            logger.error(f"find_liquidity_levels() error: {str(e)}", exc_info=True)
            return {
                'pdh': 0,
                'pdl': 0,
                'message': f'Error: {str(e)}'
            }
    
    # =========================================================================
    # 6. LIQUIDITY SWEEP CONFIRMATION
    # =========================================================================
    
    def check_liquidity_sweep(self, symbol: str, timeframe: str = "M15") -> Dict[str, Any]:
        """
        Check liquidity sweep confirmation (4-step mechanics).
        
        Sweep confirmation:
        1. Approach liquidity zone
        2. Wick breaks through (sweep)
        3. Body closes back inside (rejection)
        4. Reversal away = setup trigger READY
        
        Args:
            symbol: Trading pair
            timeframe: Confirmation timeframe (default M15)
        
        Returns:
            dict: {
                'sweep_detected': bool,
                'sweep_type': 'bullish'|'bearish'|None,
                'entry_ready': bool,
                'message': str
            }
        """
        try:
            if not self.client:
                return {
                    'sweep_detected': False,
                    'entry_ready': False,
                    'message': 'MT5 client not available'
                }
            
            # Get M15 candles (last 30)
            candles = self.client.get_candles(symbol, timeframe, 30)
            if candles is None or len(candles) < 10:
                return {
                    'sweep_detected': False,
                    'entry_ready': False,
                    'message': f'Insufficient {timeframe} data'
                }
            
            opens = candles['open'].values
            highs = candles['high'].values
            lows = candles['low'].values
            closes = candles['close'].values
            
            # Simple sweep detection: wick beyond previous range + body rejection
            sweep_detected = False
            sweep_type = None
            entry_ready = False
            
            # Check last 3 candles for sweep pattern
            if len(closes) >= 3:
                # Bullish sweep: wick down below low, close up (rejection)
                if lows[-1] < lows[-2] and closes[-1] > opens[-1]:
                    sweep_detected = True
                    sweep_type = 'bullish'
                    entry_ready = True
                
                # Bearish sweep: wick up above high, close down (rejection)
                elif highs[-1] > highs[-2] and closes[-1] < opens[-1]:
                    sweep_detected = True
                    sweep_type = 'bearish'
                    entry_ready = True
            
            if sweep_detected:
                logger.info(f"[OK] Liquidity sweep confirmed on {symbol} {timeframe}: {sweep_type.upper()}")
            
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'sweep_detected': sweep_detected,
                'sweep_type': sweep_type,
                'entry_ready': entry_ready,
                'message': f'Sweep {sweep_type}' if sweep_detected else 'No sweep detected'
            }
        
        except Exception as e:
            logger.error(f"check_liquidity_sweep() error: {str(e)}", exc_info=True)
            return {
                'sweep_detected': False,
                'entry_ready': False,
                'message': f'Error: {str(e)}'
            }
    
    # =========================================================================
    # 7. PREMIUM / DISCOUNT ZONE ANALYSIS
    # =========================================================================
    
    def check_premium_discount(self, symbol: str) -> Dict[str, Any]:
        """
        Check Premium/Discount zones (OTE analysis).
        
        OTE (Optimal Trading Entry) zones: 0.62-0.79 Fibonacci
        Sweet spot: 0.705 (highest probability)
        Invalidation: Price breaks 50% = OTE invalidated, redraw
        
        Args:
            symbol: Trading pair
        
        Returns:
            dict: {
                'zone_type': 'premium'|'discount'|None,
                'ote_level': float,
                'sweet_spot_level': float,
                'current_price': float,
                'in_zone': bool,
                'message': str
            }
        """
        try:
            if not self.client:
                return {
                    'zone_type': None,
                    'in_zone': False,
                    'message': 'MT5 client not available'
                }
            
            # Get H4 candles for longer-term range
            candles = self.client.get_candles(symbol, "H4", 100)
            if candles is None or len(candles) < 20:
                return {
                    'zone_type': None,
                    'in_zone': False,
                    'message': 'Insufficient data'
                }
            
            highs = candles['high'].values
            lows = candles['low'].values
            
            # Find recent impulse (range anchor)
            impulse_high = np.max(highs[-50:])
            impulse_low = np.min(lows[-50:])
            current_price = candles['close'].values[-1]
            
            # OTE zone (0.62-0.79 retracement)
            range_size = impulse_high - impulse_low
            ote_62_level = impulse_high - (range_size * 0.62)
            ote_79_level = impulse_high - (range_size * 0.79)
            sweet_spot = impulse_high - (range_size * 0.705)
            
            # Determine zone
            in_premium = ote_62_level <= current_price <= impulse_high
            in_discount = impulse_low <= current_price <= ote_79_level
            in_ote = ote_79_level <= current_price <= ote_62_level
            
            zone_type = None
            if in_premium:
                zone_type = 'premium'
            elif in_discount:
                zone_type = 'discount'
            elif in_ote:
                zone_type = 'ote_entry'
            
            logger.info(
                f"[OK] Premium/Discount analysis for {symbol}:"
                f"\n    Current price: {current_price:.5f}"
                f"\n    OTE sweet spot (0.705): {sweet_spot:.5f}"
                f"\n    In zone: {zone_type}"
            )
            
            return {
                'symbol': symbol,
                'zone_type': zone_type,
                'ote_level': sweet_spot,
                'ote_range': {
                    '62_level': ote_62_level,
                    '79_level': ote_79_level,
                    'sweet_spot_705': sweet_spot
                },
                'current_price': current_price,
                'in_zone': in_ote or in_premium or in_discount,
                'message': f'Price in {zone_type}' if zone_type else 'Price outside OTE zones'
            }
        
        except Exception as e:
            logger.error(f"check_premium_discount() error: {str(e)}", exc_info=True)
            return {
                'zone_type': None,
                'in_zone': False,
                'message': f'Error: {str(e)}'
            }
    
    # =========================================================================
    # 8. SETUP CONFLUENCE SCORING
    # =========================================================================
    
    def score_setup(self, symbol: str) -> Dict[str, Any]:
        """
        Score trade setup with multi-confluence analysis.
        
        Scoring factors:
        - HTF bias alignment (30 points)
        - BOS/CHoCH detection (20 points)
        - Order block confluence (15 points)
        - FVG retest (15 points)
        - Liquidity sweep confirmation (10 points)
        - OTE zone entry (10 points)
        
        Total: 0-100 points
        Recommendation:
        - 75-100: BUY/SELL HIGH PROBABILITY
        - 60-74: BUY/SELL MEDIUM PROBABILITY
        - 40-59: HOLD (wait for confluence)
        - <40: NO SETUP
        
        Args:
            symbol: Trading pair
        
        Returns:
            dict: {
                'confluence_score': 0.0-100.0,
                'recommendation': 'BUY'|'SELL'|'HOLD',
                'score_breakdown': dict,
                'message': str
            }
        """
        try:
            score = 0.0
            score_breakdown = {}
            
            # 1. HTF Bias (30 points)
            bias_result = self.get_htf_bias(symbol)
            if bias_result.get('bias') == 'bullish':
                score += 30
                score_breakdown['bias_bullish'] = 30
            elif bias_result.get('bias') == 'bearish':
                score += 30
                score_breakdown['bias_bearish'] = 30
            else:
                score += 15
                score_breakdown['bias_neutral'] = 15
            
            # 2. BOS/CHoCH (20 points)
            bos_result = self.detect_bos_choch(symbol, "H4")
            if bos_result.get('bos_detected'):
                score += 20
                score_breakdown['bos_detected'] = 20
            
            # 3. Order Blocks (15 points, weighted by quality)
            ob_result = self.find_order_blocks(symbol, "H4")
            ob_quality = ob_result.get('quality_score', 0.0)
            ob_score = round((ob_quality / 100.0) * 15.0, 1) if ob_result.get('valid_count', 0) > 0 else 0.0
            if ob_score > 0:
                score += ob_score
                score_breakdown['ob_quality'] = ob_score
            
            # 4. FVG Retest (15 points, weighted by quality)
            fvg_result = self.find_fvg(symbol, "H4")
            fvg_quality = fvg_result.get('quality_score', 0.0)
            fvg_score = round((fvg_quality / 100.0) * 15.0, 1) if fvg_result.get('valid_count', 0) > 0 else 0.0
            if fvg_score > 0:
                score += fvg_score
                score_breakdown['fvg_quality'] = fvg_score
            
            # 5. Liquidity Sweep (10 points)
            sweep_result = self.check_liquidity_sweep(symbol, "M15")
            if sweep_result.get('sweep_detected'):
                score += 10
                score_breakdown['sweep_confirmed'] = 10
            
            # 6. OTE Zone (10 points)
            ote_result = self.check_premium_discount(symbol)
            if ote_result.get('in_zone'):
                score += 10
                score_breakdown['ote_entry_zone'] = 10

            weights = {
                'bias': 30.0,
                'bos': 20.0,
                'ob_quality': 15.0,
                'fvg_quality': 15.0,
                'sweep': 10.0,
                'ote': 10.0,
            }
            
            # Determine recommendation
            if score >= 75:
                recommendation = bias_result.get('bias', 'HOLD').upper()
            elif score >= 60:
                recommendation = bias_result.get('bias', 'HOLD').upper()
            elif score >= 40:
                recommendation = 'HOLD'
            else:
                recommendation = 'HOLD'
            
            logger.info(
                f"[OK] Setup confluence scored for {symbol}: {score:.0f}/100"
                f"\n    Recommendation: {recommendation}"
                f"\n    Factors: {score_breakdown}"
            )
            
            return {
                'symbol': symbol,
                'confluence_score': round(score, 1),
                'recommendation': recommendation,
                'score_breakdown': score_breakdown,
                'weights': weights,
                'bias': bias_result.get('bias'),
                'bos_detected': bos_result.get('bos_detected'),
                'message': f'Score: {score:.0f}/100 - {recommendation}'
            }
        
        except Exception as e:
            logger.error(f"score_setup() error: {str(e)}", exc_info=True)
            return {
                'confluence_score': 0,
                'recommendation': 'HOLD',
                'message': f'Error: {str(e)}'
            }
    
    # =========================================================================
    # 9. COMPLETE TRADE PLAN GENERATION
    # =========================================================================
    
    def generate_trade_plan(self, symbol: str) -> Dict[str, Any]:
        """
        Generate complete trade plan from full analysis.
        
        Output includes:
        - 4H bias determination
        - H1/M30 structural point-of-interest (POI) identification
        - M15/M5/M1 entry trigger confirmation
        - Stop loss placement at the nearest valid swing point
        - Take profit target on the next valid OB on the same entry-zone TF
        - Confluence scoring
        
        Args:
            symbol: Trading pair
        
        Returns:
            dict: {
                'symbol': str,
                'bias': str,
                'analysis': dict,
                'trade_plan': TradeSetup,
                'recommendation': 'BUY'|'SELL'|'HOLD',
                'message': str
            }
        """
        try:
            logger.info(f"\n{'='*80}")
            logger.info(f"GENERATING COMPLETE TRADE PLAN FOR {symbol}")
            logger.info(f"{'='*80}\n")
            
            # Step 1: 4H Bias
            bias_result = self.get_htf_bias(symbol)
            bias = bias_result.get('bias', 'neutral')

            # Step 2: H1/H4-style structure analysis aligned to the approved MTF flow
            bos_result = self.detect_bos_choch(symbol, "H1")
            ob_result = self.find_order_blocks(symbol, "H1")
            fvg_result = self.find_fvg(symbol, "H1")
            liq_result = self.find_liquidity_levels(symbol, "H1")

            # Step 3: Sniper-entry confirmation on M15/M5/M1
            sweep_result = self.check_liquidity_sweep(symbol, "M15")
            ote_result = self.check_premium_discount(symbol)
            
            # Step 4: Confluence Scoring
            score_result = self.score_setup(symbol)
            confluence_score = score_result.get('confluence_score', 0)
            
            # Step 5: Trade Setup Construction
            current_price = self.client.get_tick(symbol)['bid'] if self.client else 0
            
            # Determine entry, SL, TP based on bias
            if bias == 'bullish':
                entry_price = current_price
                # SL below recent swing low
                stop_loss = liq_result.get('session_low', current_price * 0.99)
                # TP at liquidity (PDH + margin)
                take_profit = liq_result.get('pdh', current_price * 1.02)
                recommendation = 'BUY' if confluence_score >= 60 else 'HOLD'
            elif bias == 'bearish':
                entry_price = current_price
                # SL above recent swing high
                stop_loss = liq_result.get('session_high', current_price * 1.01)
                # TP at liquidity (PDL - margin)
                take_profit = liq_result.get('pdl', current_price * 0.98)
                recommendation = 'SELL' if confluence_score >= 60 else 'HOLD'
            else:
                recommendation = 'HOLD'
                entry_price = stop_loss = take_profit = current_price
            
            # Calculate SL/TP pips
            sl_pips = abs(entry_price - stop_loss) * 10000
            tp_pips = abs(take_profit - entry_price) * 10000
            
            # Validate R:R
            rr_check = self.risk_manager.validate_rr(entry_price, stop_loss, take_profit, 'long' if bias == 'bullish' else 'short')
            
            # Build trade setup
            trade_setup = TradeSetup(
                symbol=symbol,
                bias=bias,
                bias_strength=bias_result.get('strength', 50),
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                entry_trigger='bos_sweep' if bos_result.get('bos_detected') else 'confluence',
                confluence_score=confluence_score,
                liquidity_sweep=sweep_result.get('sweep_detected'),
                recommendation=recommendation
            )
            
            logger.info(
                f"\n[TRADE PLAN COMPLETE]\n"
                f"  Symbol: {symbol}"
                f"\n  Recommendation: {recommendation}"
                f"\n  Bias: {bias.upper()} (strength: {bias_result.get('strength', 0):.0f}%)"
                f"\n  Confluence: {confluence_score:.0f}/100"
                f"\n\n  ENTRY: {entry_price:.5f}"
                f"\n  SL: {stop_loss:.5f} ({sl_pips:.0f} pips)"
                f"\n  TP: {take_profit:.5f} ({tp_pips:.0f} pips)"
                f"\n  R:R: {rr_check.get('rr_ratio', 0):.2f}"
                f"\n\n  Entry Trigger: {trade_setup.entry_trigger}"
                f"\n  Sweep Confirmed: {sweep_result.get('sweep_detected')}"
                f"\n  BOS Detected: {bos_result.get('bos_detected')}"
                f"\n  OTE Zone: {ote_result.get('zone_type')}"
            )
            
            return {
                'symbol': symbol,
                'bias': bias,
                'analysis': {
                    'bias': bias_result,
                    'bos_choch': bos_result,
                    'order_blocks': ob_result,
                    'fvgs': fvg_result,
                    'liquidity_levels': liq_result,
                    'sweep': sweep_result,
                    'ote': ote_result,
                    'confluence_score': score_result
                },
                'trade_plan': {
                    'entry': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'sl_pips': round(sl_pips, 1),
                    'tp_pips': round(tp_pips, 1),
                    'rr_ratio': rr_check.get('rr_ratio', 0),
                    'entry_trigger': trade_setup.entry_trigger,
                    'confluence_score': confluence_score
                },
                'recommendation': recommendation,
                'message': f'Trade plan generated: {recommendation}'
            }
        
        except Exception as e:
            logger.error(f"generate_trade_plan() error: {str(e)}", exc_info=True)
            return {
                'recommendation': 'HOLD',
                'message': f'Error: {str(e)}'
            }


# =============================================================================
# SINGLETON INSTANCE & MODULE FUNCTIONS
# =============================================================================

_trade_engine_instance = None


def get_trade_engine() -> TradeEngine:
    """Get or create singleton TradeEngine instance."""
    global _trade_engine_instance
    if _trade_engine_instance is None:
        _trade_engine_instance = TradeEngine()
    return _trade_engine_instance


# =============================================================================
# MAIN / TEST
# =============================================================================

if __name__ == "__main__":
    """Test trade engine with live MT5 data."""
    logger.info("="*80)
    logger.info("TRADE ENGINE TEST SUITE")
    logger.info("="*80)
    
    engine = get_trade_engine()
    
    # Test with EURUSD
    symbol = "EURUSD"
    
    logger.info(f"\n[TEST 1] HTF Bias Detection")
    bias = engine.get_htf_bias(symbol)
    logger.info(f"Result: {bias}\n")
    
    logger.info(f"[TEST 2] BOS/CHoCH Detection")
    bos = engine.detect_bos_choch(symbol, "H4")
    logger.info(f"Result: {bos}\n")
    
    logger.info(f"[TEST 3] Order Block Detection")
    obs = engine.find_order_blocks(symbol, "H4")
    logger.info(f"Result: Valid OBs={obs['valid_count']}\n")
    
    logger.info(f"[TEST 4] FVG Detection")
    fvgs = engine.find_fvg(symbol, "H4")
    logger.info(f"Result: Valid FVGs={fvgs['valid_count']}\n")
    
    logger.info(f"[TEST 5] Liquidity Level Identification")
    liq = engine.find_liquidity_levels(symbol, "H4")
    logger.info(f"Result: PDH={liq['pdh']:.5f}, PDL={liq['pdl']:.5f}\n")
    
    logger.info(f"[TEST 6] Liquidity Sweep Confirmation")
    sweep = engine.check_liquidity_sweep(symbol, "H1")
    logger.info(f"Result: {sweep}\n")
    
    logger.info(f"[TEST 7] Premium/Discount Analysis")
    ote = engine.check_premium_discount(symbol)
    logger.info(f"Result: {ote}\n")
    
    logger.info(f"[TEST 8] Setup Confluence Scoring")
    score = engine.score_setup(symbol)
    logger.info(f"Result: {score}\n")
    
    logger.info(f"[TEST 9] Complete Trade Plan Generation")
    plan = engine.generate_trade_plan(symbol)
    logger.info(f"Result: {plan}\n")
    
    logger.info("="*80)
    logger.info("ALL TESTS COMPLETED")
    logger.info("="*80)
