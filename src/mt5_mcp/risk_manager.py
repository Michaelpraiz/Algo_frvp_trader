"""
RISK MANAGER — Phase 3.1
===============================================
Comprehensive risk management & position sizing for SMC trading strategy.
Enforces all risk rules from strategy_config.py:
- Position sizing (lot calculation)
- Daily drawdown limits
- Max concurrent positions
- Spread validation
- R:R guardrails
- News event filtering
- Consecutive loss tracking
"""

import logging
import sys
from typing import Dict, Optional, Tuple, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json
import os

# Import local modules
from .mt5_client import get_client
from .strategy_config import (
    RISK_MANAGEMENT, 
    FILTERS, 
    POSITION_MANAGEMENT,
    TIMEFRAMES,
    SESSIONS
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - RISK_MANAGER - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/risk_manager.log"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class TradeSetup:
    """Represents a potential trade setup for validation."""
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    sl_pips: float
    tp_pips: float
    risk_percent: Optional[float] = None
    
    def __post_init__(self):
        """Calculate R:R if not provided."""
        if self.sl_pips > 0:
            self.rr = self.tp_pips / self.sl_pips
        else:
            self.rr = 0


@dataclass
class DailyStats:
    """Tracks daily trading statistics."""
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    trades_today: int = 0
    daily_pnl: float = 0.0
    daily_pnl_percent: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    largest_loss: float = 0.0
    largest_win: float = 0.0
    total_risk_used: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "date": self.date,
            "trades_today": self.trades_today,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_percent": round(self.daily_pnl_percent, 2),
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "largest_loss": round(self.largest_loss, 2),
            "largest_win": round(self.largest_win, 2),
            "total_risk_used": round(self.total_risk_used, 2),
        }


# =============================================================================
# RISK MANAGER CLASS
# =============================================================================

class RiskManager:
    """
    Comprehensive risk management system for SMC trading.
    Enforces all position sizing, leverage, and risk rules.
    """
    
    def __init__(self):
        """Initialize risk manager with strategy parameters."""
        self.client = get_client()
        
        # Load configuration
        self.risk_config = RISK_MANAGEMENT
        self.filters = FILTERS
        self.position_mgmt = POSITION_MANAGEMENT
        
        # Risk parameters
        self.risk_per_trade = self.risk_config.get("risk_per_trade_percent", 10.0)
        self.max_daily_risk = self.risk_config.get("max_daily_risk_percent", 10.0)
        self.max_open_trades = self.risk_config.get("max_open_trades", 2)
        self.total_risk_per_max_open = self.risk_config.get("total_risk_per_max_open_trades", 10.0)
        self.max_trades_per_day = self.risk_config.get("max_trades_per_day", 10)

        # R:R guardrails
        self.min_rr = self.filters.get("min_rr_to_take_trade", 3.0)
        self.max_rr = self.filters.get("max_rr_to_take_trade", 5.0)

        # Consecutive loss tracking
        self.consecutive_loss_config = self.risk_config.get("consecutive_loss_tracking", {})
        self.consecutive_losses = 0
        self.loss_reduction_active = False
        self.loss_reduction_trades_remaining = 0
        self.reduced_risk_percent = self.consecutive_loss_config.get("reduction_action", {}).get("reduce_risk_to_percent", 10.0)
        
        # Daily statistics
        self.daily_stats = DailyStats()
        self.stats_file = f"logs/daily_stats_{datetime.now().strftime('%Y-%m-%d')}.json"
        
        # Spread limits (from FILTERS)
        self.spread_limits = self.filters.get("spread_max_pips", {})
        
        logger.info("[OK] Risk Manager initialized")
        logger.info(f"  Risk per trade: {self.risk_per_trade}%")
        logger.info(f"  Max daily risk: {self.max_daily_risk}%")
        logger.info(f"  Max open trades: {self.max_open_trades}")
        logger.info(f"  R:R guardrails: {self.min_rr}-{self.max_rr}")
    
    # =========================================================================
    # CORE RISK FUNCTIONS
    # =========================================================================
    
    def calculate_lot_size(
        self,
        symbol: str,
        sl_pips: float,
        risk_percent: Optional[float] = None,
        position_index: int = 1
    ) -> Dict[str, Any]:
        """
        Calculate position size (lot size) based on risk parameters.
        
        Uses formula: Lot Size = Risk Amount / (SL Pips × Pip Value per Lot)
        
        Args:
            symbol: Trading pair (e.g., 'EURUSD')
            sl_pips: Stop loss distance in pips
            risk_percent: % of account to risk (if None, use config default)
            position_index: Position number (1 or 2) for multi-position splits
        
        Returns:
            dict: {
                'lot_size': float,
                'risk_amount': float,
                'account_balance': float,
                'status': 'success' or error message
            }
        """
        try:
            if not self.client:
                return {
                    "lot_size": 0,
                    "risk_amount": 0,
                    "account_balance": 0,
                    "status": "Error: MT5 client not available"
                }
            
            # Get account info
            account_info = self.client.get_account_info()
            if not account_info:
                return {
                    "lot_size": 0,
                    "risk_amount": 0,
                    "account_balance": 0,
                    "status": "Error: Could not retrieve account info"
                }
            
            account_balance = account_info.get("balance", 0)
            if account_balance <= 0:
                return {
                    "lot_size": 0,
                    "risk_amount": 0,
                    "account_balance": 0,
                    "status": "Error: Account balance is zero or negative"
                }
            
            # Determine risk percentage
            if risk_percent is None:
                # Check if consecutive loss reduction is active
                if self.loss_reduction_active:
                    risk_percent = self.reduced_risk_percent
                    logger.info(f"  Consecutive losses detected — using reduced risk: {risk_percent}%")
                else:
                    risk_percent = self.risk_per_trade
            
            # For 2-position entries, split risk equally
            if position_index == 2:
                # Second position gets half the risk
                risk_percent = risk_percent / 2
            
            # Calculate risk amount
            risk_amount = account_balance * (risk_percent / 100.0)
            
            # Validate SL pips
            if sl_pips <= 0:
                return {
                    "lot_size": 0,
                    "risk_amount": 0,
                    "account_balance": account_balance,
                    "status": f"Error: Invalid SL pips ({sl_pips})"
                }
            
            # Pip value is typically $10 per pip per standard lot in forex
            # For other instruments, this might vary
            pip_value = 10.0  # $ per pip per lot (standard forex)
            
            # Calculate lot size
            lot_size = risk_amount / (sl_pips * pip_value)
            
            # Round to valid lot increment (MT5 typically allows 0.01 lot)
            lot_size = round(lot_size, 2)
            
            # Validate lot size
            if lot_size < 0.01:
                logger.warning(f"Calculated lot size {lot_size} is too small for {symbol}")
                lot_size = 0.01
            
            logger.info(
                f"[OK] Lot size calculated for {symbol}:"
                f"\n    Account: ${account_balance:,.2f}"
                f"\n    Risk %: {risk_percent}%"
                f"\n    Risk Amount: ${risk_amount:,.2f}"
                f"\n    SL Distance: {sl_pips} pips"
                f"\n    Lot Size: {lot_size} lots"
            )
            
            return {
                "lot_size": lot_size,
                "risk_amount": round(risk_amount, 2),
                "account_balance": account_balance,
                "risk_percent": risk_percent,
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"calculate_lot_size() error: {str(e)}", exc_info=True)
            return {
                "lot_size": 0,
                "risk_amount": 0,
                "account_balance": 0,
                "status": f"Error: {str(e)}"
            }
    
    def validate_rr(
        self,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        side: str = "long"
    ) -> Dict[str, Any]:
        """
        Validate Risk:Reward ratio against guardrails.
        
        Args:
            entry_price: Entry price level
            stop_loss_price: Stop loss price level
            take_profit_price: Take profit price level
            side: 'long' or 'short'
        
        Returns:
            dict: {
                'rr_ratio': float,
                'valid': bool,
                'message': str,
                'recommendation': str
            }
        """
        try:
            # Calculate distances in pips (assuming 4 decimals = 1 pip)
            if side.lower() == "long":
                sl_pips = (entry_price - stop_loss_price) * 10000
                tp_pips = (take_profit_price - entry_price) * 10000
            else:  # short
                sl_pips = (stop_loss_price - entry_price) * 10000
                tp_pips = (entry_price - take_profit_price) * 10000
            
            # Validate distances are positive
            if sl_pips <= 0 or tp_pips <= 0:
                return {
                    "rr_ratio": 0,
                    "valid": False,
                    "message": f"Invalid prices: Entry={entry_price}, SL={stop_loss_price}, TP={take_profit_price}",
                    "recommendation": "Check entry/SL/TP levels"
                }
            
            # Calculate R:R
            rr_ratio = tp_pips / sl_pips
            
            # Check guardrails
            if rr_ratio < self.min_rr:
                return {
                    "rr_ratio": round(rr_ratio, 2),
                    "valid": False,
                    "message": f"R:R {rr_ratio:.2f} is below minimum {self.min_rr}",
                    "recommendation": f"REJECT TRADE — Insufficient reward. Move TP higher or SL lower.",
                    "sl_pips": round(sl_pips, 1),
                    "tp_pips": round(tp_pips, 1)
                }
            elif rr_ratio > self.max_rr:
                return {
                    "rr_ratio": round(rr_ratio, 2),
                    "valid": True,
                    "message": f"R:R {rr_ratio:.2f} exceeds maximum {self.max_rr}",
                    "recommendation": f"CAP TP at 1:{self.max_rr} ratio. Risk still acceptable but overreaching.",
                    "capped_rr": self.max_rr,
                    "sl_pips": round(sl_pips, 1),
                    "tp_pips": round(tp_pips, 1)
                }
            else:
                return {
                    "rr_ratio": round(rr_ratio, 2),
                    "valid": True,
                    "message": f"R:R {rr_ratio:.2f} is within guardrails ({self.min_rr}-{self.max_rr})",
                    "recommendation": "ACCEPT TRADE",
                    "sl_pips": round(sl_pips, 1),
                    "tp_pips": round(tp_pips, 1)
                }
        
        except Exception as e:
            logger.error(f"validate_rr() error: {str(e)}", exc_info=True)
            return {
                "rr_ratio": 0,
                "valid": False,
                "message": f"Error: {str(e)}",
                "recommendation": "Contact support"
            }
    
    def check_spread(self, symbol: str) -> Dict[str, Any]:
        """
        Check current spread against configured limits.
        
        Args:
            symbol: Trading pair (e.g., 'EURUSD')
        
        Returns:
            dict: {
                'symbol': str,
                'bid': float,
                'ask': float,
                'spread_pips': float,
                'spread_limit': float,
                'valid': bool,
                'message': str
            }
        """
        try:
            if not self.client:
                return {
                    "symbol": symbol,
                    "spread_pips": 0,
                    "valid": False,
                    "message": "MT5 client not available"
                }
            
            # Get current tick
            tick = self.client.get_tick(symbol)
            if not tick:
                return {
                    "symbol": symbol,
                    "spread_pips": 0,
                    "valid": False,
                    "message": f"Could not retrieve tick for {symbol}"
                }
            
            bid = tick.get("bid", 0)
            ask = tick.get("ask", 0)
            spread = ask - bid
            spread_pips = spread * 10000  # Convert to pips
            
            # Get spread limit for this symbol
            spread_limit = self.spread_limits.get(symbol, 5.0)
            
            # Validate
            valid = spread_pips <= spread_limit
            
            if valid:
                logger.info(f"[OK] {symbol} spread OK: {spread_pips:.1f} pips (limit: {spread_limit})")
            else:
                logger.warning(f"[FAIL] {symbol} spread REJECTED: {spread_pips:.1f} pips (limit: {spread_limit})")
            
            return {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "spread_pips": round(spread_pips, 1),
                "spread_limit": spread_limit,
                "valid": valid,
                "message": "Spread OK" if valid else f"Spread too wide: {spread_pips:.1f} > {spread_limit}"
            }
        
        except Exception as e:
            logger.error(f"check_spread() error: {str(e)}", exc_info=True)
            return {
                "symbol": symbol,
                "spread_pips": 0,
                "valid": False,
                "message": f"Error: {str(e)}"
            }
    
    def check_max_open_trades(self) -> Dict[str, Any]:
        """
        Check if we've reached maximum concurrent positions.
        
        Returns:
            dict: {
                'current_open_trades': int,
                'max_allowed': int,
                'can_enter': bool,
                'message': str
            }
        """
        try:
            if not self.client:
                return {
                    "current_open_trades": 0,
                    "max_allowed": self.max_open_trades,
                    "can_enter": False,
                    "message": "MT5 client not available"
                }
            
            # Get open positions
            positions = self.client.get_open_positions()
            current_open = len(positions) if positions else 0
            
            can_enter = current_open < self.max_open_trades
            
            if can_enter:
                logger.info(f"[OK] Position limit OK: {current_open}/{self.max_open_trades} positions open")
            else:
                logger.warning(f"[FAIL] Position limit REACHED: {current_open}/{self.max_open_trades} positions")
            
            return {
                "current_open_trades": current_open,
                "max_allowed": self.max_open_trades,
                "can_enter": can_enter,
                "positions": positions if positions else [],
                "message": f"Can enter: {current_open} of {self.max_open_trades} slots used"
            }
        
        except Exception as e:
            logger.error(f"check_max_open_trades() error: {str(e)}", exc_info=True)
            return {
                "current_open_trades": 0,
                "max_allowed": self.max_open_trades,
                "can_enter": False,
                "message": f"Error: {str(e)}"
            }
    
    def check_daily_drawdown(self) -> Dict[str, Any]:
        """
        Check daily P&L against drawdown limit.
        Halts trading if max daily loss is exceeded.
        
        Returns:
            dict: {
                'daily_pnl': float,
                'daily_pnl_percent': float,
                'max_daily_risk': float,
                'can_trade': bool,
                'message': str
            }
        """
        try:
            if not self.client:
                return {
                    "daily_pnl": 0,
                    "daily_pnl_percent": 0,
                    "max_daily_risk": self.max_daily_risk,
                    "can_trade": False,
                    "message": "MT5 client not available"
                }
            
            # Get account info
            account_info = self.client.get_account_info()
            if not account_info:
                return {
                    "daily_pnl": 0,
                    "daily_pnl_percent": 0,
                    "max_daily_risk": self.max_daily_risk,
                    "can_trade": False,
                    "message": "Could not retrieve account info"
                }
            
            balance = account_info.get("balance", 0)
            equity = account_info.get("equity", 0)
            
            # Calculate daily P&L
            daily_pnl = equity - balance
            daily_pnl_percent = (daily_pnl / balance * 100) if balance > 0 else 0
            
            # Check against limit
            can_trade = abs(daily_pnl_percent) <= self.max_daily_risk
            
            # Update daily stats
            self.daily_stats.daily_pnl = daily_pnl
            self.daily_stats.daily_pnl_percent = daily_pnl_percent
            
            if can_trade:
                logger.info(
                    f"[OK] Daily drawdown OK: {daily_pnl:+.2f} USD ({daily_pnl_percent:+.2f}% | "
                    f"limit: {self.max_daily_risk}%)"
                )
            else:
                logger.error(
                    f"[FAIL] Daily drawdown LIMIT HIT: {daily_pnl:+.2f} USD ({daily_pnl_percent:+.2f}% | "
                    f"limit: {self.max_daily_risk}%)"
                )
                logger.error("[WARNING] TRADING HALTED FOR THE DAY")
            
            return {
                "daily_pnl": round(daily_pnl, 2),
                "daily_pnl_percent": round(daily_pnl_percent, 2),
                "max_daily_risk": self.max_daily_risk,
                "can_trade": can_trade,
                "message": "Daily limit OK" if can_trade else f"Daily loss limit hit: {abs(daily_pnl_percent):.2f}% vs {self.max_daily_risk}%"
            }
        
        except Exception as e:
            logger.error(f"check_daily_drawdown() error: {str(e)}", exc_info=True)
            return {
                "daily_pnl": 0,
                "daily_pnl_percent": 0,
                "max_daily_risk": self.max_daily_risk,
                "can_trade": False,
                "message": f"Error: {str(e)}"
            }
    
    def is_news_time(self, check_minutes_before: int = 30, check_minutes_after: int = 15) -> Dict[str, Any]:
        """
        Basic news event filter (stub implementation).
        
        In production, this would check against an economic calendar API
        (e.g., Investing.com, Forexfactory, OANDA calendar).
        
        Args:
            check_minutes_before: Minutes before event to avoid
            check_minutes_after: Minutes after event to avoid
        
        Returns:
            dict: {
                'is_news_time': bool,
                'message': str,
                'can_trade': bool
            }
        """
        try:
            # Get current time
            current_time = datetime.now()
            
            # TODO: Integrate with real economic calendar API
            # For now, return False (not in news time)
            # This is a placeholder for Phase 4 integration
            
            is_news = False
            can_trade = True
            message = "No high-impact news detected (placeholder)"
            
            if is_news:
                logger.warning(f"[WARNING] High-impact news detected — trading disabled for +/-{check_minutes_before}/{check_minutes_after} min")
            
            return {
                "is_news_time": is_news,
                "current_time": current_time.isoformat(),
                "can_trade": can_trade,
                "message": message,
                "note": "Integration with economic calendar API required for Phase 4"
            }
        
        except Exception as e:
            logger.error(f"is_news_time() error: {str(e)}", exc_info=True)
            return {
                "is_news_time": False,
                "can_trade": True,
                "message": f"Error: {str(e)}"
            }
    
    # =========================================================================
    # POSITION REDUCTION & LOSS TRACKING
    # =========================================================================
    
    def record_trade_outcome(self, pnl: float, side: str = "long") -> Dict[str, Any]:
        """
        Record trade outcome and update consecutive loss counter.
        Triggers position reduction if consecutive losses threshold is hit.
        
        Args:
            pnl: Profit/loss in USD
            side: 'long' or 'short' (for reference)
        
        Returns:
            dict: {
                'consecutive_losses': int,
                'loss_reduction_active': bool,
                'reduced_risk_percent': float,
                'message': str
            }
        """
        try:
            if pnl < 0:
                self.consecutive_losses += 1
                self.daily_stats.consecutive_wins = 0
                self.daily_stats.consecutive_losses = self.consecutive_losses
                self.daily_stats.largest_loss = min(self.daily_stats.largest_loss, pnl)
                
                logger.warning(f"Loss recorded: {pnl:+.2f} USD | Consecutive losses: {self.consecutive_losses}")
            else:
                self.consecutive_losses = 0
                self.loss_reduction_active = False
                self.loss_reduction_trades_remaining = 0
                self.daily_stats.consecutive_wins += 1
                self.daily_stats.consecutive_losses = 0
                self.daily_stats.largest_win = max(self.daily_stats.largest_win, pnl)
                
                logger.info(f"Win recorded: {pnl:+.2f} USD | Consecutive wins: {self.daily_stats.consecutive_wins}")
            
            # Check for loss threshold
            threshold = self.consecutive_loss_config.get("consecutive_losses_threshold", 2)
            if self.consecutive_losses >= threshold and not self.loss_reduction_active:
                self.loss_reduction_active = True
                self.loss_reduction_trades_remaining = self.consecutive_loss_config.get("reduction_action", {}).get("apply_for_next_n_trades", 3)
                
                logger.error(
                    f"[WARNING] CONSECUTIVE LOSS THRESHOLD HIT ({self.consecutive_losses} losses)"
                    f"\n    Activating position reduction: {self.risk_per_trade}% → {self.reduced_risk_percent}%"
                    f"\n    Duration: next {self.loss_reduction_trades_remaining} trades"
                )
                
                return {
                    "consecutive_losses": self.consecutive_losses,
                    "loss_reduction_active": True,
                    "reduced_risk_percent": self.reduced_risk_percent,
                    "duration_trades": self.loss_reduction_trades_remaining,
                    "message": f"Position reduction ACTIVATED for next {self.loss_reduction_trades_remaining} trades"
                }
            
            # Decrement reduction countdown
            if self.loss_reduction_active and self.loss_reduction_trades_remaining > 0:
                self.loss_reduction_trades_remaining -= 1
                if self.loss_reduction_trades_remaining == 0:
                    self.loss_reduction_active = False
                    logger.info("Position reduction period ENDED — returning to normal risk")
            
            return {
                "consecutive_losses": self.consecutive_losses,
                "loss_reduction_active": self.loss_reduction_active,
                "reduced_risk_percent": self.reduced_risk_percent if self.loss_reduction_active else self.risk_per_trade,
                "message": "Trade recorded"
            }
        
        except Exception as e:
            logger.error(f"record_trade_outcome() error: {str(e)}", exc_info=True)
            return {
                "consecutive_losses": self.consecutive_losses,
                "loss_reduction_active": self.loss_reduction_active,
                "message": f"Error: {str(e)}"
            }
    
    # =========================================================================
    # UTILITY FUNCTIONS
    # =========================================================================
    
    def save_daily_stats(self) -> bool:
        """Save daily statistics to JSON file."""
        try:
            with open(self.stats_file, "w") as f:
                json.dump(self.daily_stats.to_dict(), f, indent=2)
            logger.info(f"Daily stats saved to {self.stats_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save daily stats: {str(e)}")
            return False
    
    def get_daily_stats(self) -> Dict[str, Any]:
        """Get current daily statistics."""
        return self.daily_stats.to_dict()


# =============================================================================
# SINGLETON INSTANCE & MODULE FUNCTIONS
# =============================================================================

_risk_manager_instance: Optional[RiskManager] = None


def get_risk_manager() -> RiskManager:
    """Get or create singleton RiskManager instance."""
    global _risk_manager_instance
    if _risk_manager_instance is None:
        _risk_manager_instance = RiskManager()
    return _risk_manager_instance


def close_risk_manager() -> None:
    """Clean up risk manager instance."""
    global _risk_manager_instance
    if _risk_manager_instance:
        _risk_manager_instance.save_daily_stats()
        _risk_manager_instance = None


# =============================================================================
# MODULE-LEVEL CONVENIENCE FUNCTIONS
# =============================================================================

def calculate_lot_size(
    symbol: str,
    sl_pips: float,
    risk_percent: Optional[float] = None
) -> Dict[str, Any]:
    """Convenience function — calculate lot size."""
    return get_risk_manager().calculate_lot_size(symbol, sl_pips, risk_percent)


def validate_rr(
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    side: str = "long"
) -> Dict[str, Any]:
    """Convenience function — validate R:R."""
    return get_risk_manager().validate_rr(entry_price, stop_loss_price, take_profit_price, side)


def check_spread(symbol: str) -> Dict[str, Any]:
    """Convenience function — check spread."""
    return get_risk_manager().check_spread(symbol)


def check_max_open_trades() -> Dict[str, Any]:
    """Convenience function — check max open positions."""
    return get_risk_manager().check_max_open_trades()


def check_daily_drawdown() -> Dict[str, Any]:
    """Convenience function — check daily drawdown."""
    return get_risk_manager().check_daily_drawdown()


def is_news_time() -> Dict[str, Any]:
    """Convenience function — check if in news event time."""
    return get_risk_manager().is_news_time()


# =============================================================================
# MAIN / TEST
# =============================================================================

if __name__ == "__main__":
    """Test risk manager functions."""
    logger.info("=" * 80)
    logger.info("RISK MANAGER TEST SUITE")
    logger.info("=" * 80)
    
    rm = get_risk_manager()
    
    # Test 1: Lot Size Calculation
    logger.info("\n[TEST 1] Lot Size Calculation")
    lot_result = rm.calculate_lot_size("EURUSD", sl_pips=20.0, risk_percent=5.0)
    logger.info(f"Result: {lot_result}")
    
    # Test 2: R:R Validation (VALID)
    logger.info("\n[TEST 2] R:R Validation (Valid Setup)")
    rr_result = rm.validate_rr(
        entry_price=1.1050,
        stop_loss_price=1.1020,
        take_profit_price=1.1110,
        side="long"
    )
    logger.info(f"Result: {rr_result}")
    
    # Test 3: R:R Validation (INVALID - too low)
    logger.info("\n[TEST 3] R:R Validation (Invalid - Too Low)")
    rr_result = rm.validate_rr(
        entry_price=1.1050,
        stop_loss_price=1.1020,
        take_profit_price=1.1070,
        side="long"
    )
    logger.info(f"Result: {rr_result}")
    
    # Test 4: Spread Check
    logger.info("\n[TEST 4] Spread Validation")
    spread_result = rm.check_spread("EURUSD")
    logger.info(f"Result: {spread_result}")
    
    # Test 5: Max Open Positions
    logger.info("\n[TEST 5] Max Open Positions Check")
    positions_result = rm.check_max_open_trades()
    logger.info(f"Result: {positions_result}")
    
    # Test 6: Daily Drawdown
    logger.info("\n[TEST 6] Daily Drawdown Check")
    drawdown_result = rm.check_daily_drawdown()
    logger.info(f"Result: {drawdown_result}")
    
    # Test 7: News Time Check
    logger.info("\n[TEST 7] News Time Check")
    news_result = rm.is_news_time()
    logger.info(f"Result: {news_result}")
    
    logger.info("\n" + "=" * 80)
    logger.info("ALL TESTS COMPLETED")
    logger.info("=" * 80)
    
    close_risk_manager()
