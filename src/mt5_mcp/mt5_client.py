"""
MT5 Connection Layer — Phase 2.1
===============================================
Provides a clean, robust wrapper around MetaTrader5 API.
- MT5 initialization & authentication
- Connection health checks & auto-reconnect
- Exposed functions for account, market data, and order info
"""

import os
import sys
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, timezone
import MetaTrader5 as mt5
import pandas as pd

from .config import ACCOUNT_TYPE, get_setting

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - MT5_CLIENT - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/mt5_client.log"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# MT5 CONNECTION MANAGER
# =============================================================================

class MT5Client:
    """
    Manages MT5 connection lifecycle, health checks, and API access.
    """
    
    def __init__(self):
        """Initialize MT5 client with configuration from .env"""
        self.login = get_setting("MT5_LOGIN")
        self.password = get_setting("MT5_PASSWORD")
        self.server = get_setting("MT5_SERVER")
        self.account_type = ACCOUNT_TYPE
        
        self.is_connected = False
        self.last_check = None
        self.connection_attempts = 0
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        
        # Validate credentials
        if not all([self.login, self.password, self.server]):
            raise ValueError(
                "Missing MT5 credentials in .env. "
                "Please fill in MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER."
            )
        
        logger.info(f"MT5 Client initialized - Account Type: {self.account_type}")
    
    def connect(self) -> bool:
        """
        Initialize and authenticate MT5 connection.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Initialize MT5 application
            if not mt5.initialize():
                logger.error(f"MT5 initialize() failed: {mt5.last_error()}")
                return False
            
            logger.info("MT5 application initialized")
            
            # Attempt login
            account_number = int(self.login)
            if not mt5.login(
                login=account_number,
                password=self.password,
                server=self.server
            ):
                error = mt5.last_error()
                logger.error(f"MT5 login failed for {account_number}: {error}")
                mt5.shutdown()
                return False
            
            self.is_connected = True
            self.connection_attempts = 0
            logger.info(f"[OK] Connected to MT5 - {self.server} (Account: {account_number})")
            
            return True
            
        except Exception as e:
            logger.error(f"Connection error: {str(e)}", exc_info=True)
            return False
    
    def disconnect(self) -> None:
        """Gracefully disconnect from MT5."""
        try:
            mt5.shutdown()
            self.is_connected = False
            logger.info("✓ MT5 connection closed")
        except Exception as e:
            logger.error(f"Error during disconnect: {str(e)}")
    
    def health_check(self) -> bool:
        """
        Check connection health. Auto-reconnect if needed.
        
        Returns:
            bool: True if connected and healthy, False otherwise
        """
        try:
            # Try a simple query to test connection
            if not self.is_connected:
                logger.warning("Connection lost, attempting reconnect...")
                return self._reconnect()
            
            # Query account info as health check
            account_info = mt5.account_info()
            if account_info is None:
                logger.warning("Health check failed, reconnecting...")
                return self._reconnect()
            
            self.last_check = datetime.now()
            return True
            
        except Exception as e:
            logger.error(f"Health check error: {str(e)}")
            return self._reconnect()
    
    def _reconnect(self) -> bool:
        """
        Attempt to reconnect after connection loss.
        
        Returns:
            bool: True if reconnection successful, False otherwise
        """
        if self.connection_attempts >= self.max_retries:
            logger.error("Max reconnection attempts exceeded")
            return False
        
        self.connection_attempts += 1
        logger.info(f"Reconnection attempt {self.connection_attempts}/{self.max_retries}...")
        
        try:
            mt5.shutdown()
            time.sleep(self.retry_delay)
            return self.connect()
        except Exception as e:
            logger.error(f"Reconnection failed: {str(e)}")
            return False
    
    # =========================================================================
    # ACCOUNT INFORMATION
    # =========================================================================
    
    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve account information (balance, equity, margin, etc.).
        
        Returns:
            dict: Account info with keys like balance, equity, free_margin, margin_level
            None: If query fails
        """
        try:
            if not self.health_check():
                logger.error("Cannot get account info - connection unhealthy")
                return None
            
            account = mt5.account_info()
            if account is None:
                logger.error(f"account_info() failed: {mt5.last_error()}")
                return None
            
            info = {
                "login": account.login,
                "name": account.name,
                "server": account.server,
                "account_type": "demo" if account.trade_mode == 1 else "live",
                "balance": account.balance,
                "equity": account.equity,
                "profit": account.profit,
                "free_margin": account.margin_free,
                "used_margin": account.margin,
                "margin_level": round(account.margin_level, 2) if account.margin_level else 0,
                "leverage": account.leverage,
                "currency": account.currency,
            }
            
            logger.debug(f"✓ Account info retrieved: Balance={info['balance']}")
            return info
            
        except Exception as e:
            logger.error(f"get_account_info() error: {str(e)}", exc_info=True)
            return None
    
    # =========================================================================
    # SYMBOL INFORMATION
    # =========================================================================
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve symbol specifications (contract size, digits, stops, etc.).
        
        Args:
            symbol (str): Trading pair symbol (e.g., 'EURUSD')
        
        Returns:
            dict: Symbol info with contract_size, digits, min_volume, max_volume, etc.
            None: If symbol not found
        """
        try:
            if not self.health_check():
                return None
            
            sym_info = mt5.symbol_info(symbol)
            if sym_info is None:
                logger.error(f"Symbol '{symbol}' not found: {mt5.last_error()}")
                return None
            
            info = {
                "symbol": sym_info.name,
                "description": sym_info.description,
                "contract_size": sym_info.trade_contract_size,
                "digits": sym_info.digits,
                "point": sym_info.point,
                "bid": sym_info.bid,
                "ask": sym_info.ask,
                "last": sym_info.last,
                "bid_volume": getattr(sym_info, "bid_volume", 0.0),
                "ask_volume": getattr(sym_info, "ask_volume", 0.0),
                "min_volume": sym_info.volume_min,
                "max_volume": sym_info.volume_max,
                "min_volume_step": sym_info.volume_step,
                "min_stop_distance": sym_info.trade_stops_level,
                "spread": sym_info.spread,
                "spread_points": getattr(sym_info, "spread_raw", sym_info.spread),
                "trade_tick_size": getattr(sym_info, "trade_tick_size", sym_info.point),
                "trade_tick_value": getattr(sym_info, "trade_tick_value", 0.0),
                "trade_tick_value_loss": getattr(sym_info, "trade_tick_value_loss", 0.0),
                "trade_tick_value_profit": getattr(sym_info, "trade_tick_value_profit", 0.0),
                "currency_profit": getattr(sym_info, "currency_profit", ""),
                "trade_stops_level": getattr(sym_info, "trade_stops_level", 0),
                "trade_freeze_level": getattr(sym_info, "trade_freeze_level", 0),
                "volume_min": getattr(sym_info, "volume_min", 0.0),
                "volume_max": getattr(sym_info, "volume_max", 0.0),
                "volume_step": getattr(sym_info, "volume_step", 0.0),
                "trade_contract_size": getattr(sym_info, "trade_contract_size", 0.0),
            }
            
            logger.debug(f"✓ Symbol info retrieved: {symbol} @ {info['bid']}/{info['ask']}")
            return info
            
        except Exception as e:
            logger.error(f"get_symbol_info({symbol}) error: {str(e)}", exc_info=True)
            return None
    
    # =========================================================================
    # MARKET DATA
    # =========================================================================
    
    def get_candles(self, symbol: str, timeframe_str: str, count: int) -> Optional[pd.DataFrame]:
        """
        Retrieve candlestick data (OHLCV).
        
        Args:
            symbol (str): Trading pair (e.g., 'EURUSD')
            timeframe_str (str): Timeframe ('M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN1')
            count (int): Number of candles to retrieve
        
        Returns:
            pd.DataFrame: DataFrame with columns [time, open, high, low, close, volume]
            None: If request fails
        """
        try:
            if not self.health_check():
                return None
            
            # Map timeframe strings to MT5 constants
            timeframe_map = {
                'M1': mt5.TIMEFRAME_M1,
                'M5': mt5.TIMEFRAME_M5,
                'M15': mt5.TIMEFRAME_M15,
                'M30': mt5.TIMEFRAME_M30,
                'H1': mt5.TIMEFRAME_H1,
                'H4': mt5.TIMEFRAME_H4,
                'D1': mt5.TIMEFRAME_D1,
                'W1': mt5.TIMEFRAME_W1,
                'MN1': mt5.TIMEFRAME_MN1,
            }
            
            if timeframe_str not in timeframe_map:
                logger.error(f"Invalid timeframe: {timeframe_str}. Valid: {list(timeframe_map.keys())}")
                return None
            
            timeframe = timeframe_map[timeframe_str]
            
            # Retrieve candles
            candles = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if candles is None:
                logger.error(f"Failed to get candles {symbol} {timeframe_str}: {mt5.last_error()}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(candles)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']].copy()
            df.rename(columns={'tick_volume': 'volume'}, inplace=True)
            
            logger.debug(f"✓ Retrieved {len(df)} candles: {symbol} {timeframe_str}")
            return df
            
        except Exception as e:
            logger.error(f"get_candles({symbol}, {timeframe_str}) error: {str(e)}", exc_info=True)
            return None

    def get_candles_range(
        self, symbol: str, timeframe_str: str, start: datetime, end: datetime
    ) -> Optional[pd.DataFrame]:
        """Retrieve historical OHLCV bars for a bounded UTC interval."""
        timeframe_map = {
            "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
        }
        if timeframe_str not in timeframe_map:
            raise ValueError(f"Invalid timeframe: {timeframe_str}")
        if start >= end:
            raise ValueError("start must be earlier than end")
        if not self.health_check():
            raise ConnectionError("Cannot retrieve historical candles: MT5 connection is unhealthy")
        rates = mt5.copy_rates_range(symbol, timeframe_map[timeframe_str], start, end)
        if rates is None:
            raise RuntimeError(f"MT5 candle-range request failed: {mt5.last_error()}")
        if len(rates) == 0:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        data = pd.DataFrame(rates)
        data["time"] = pd.to_datetime(data["time"], unit="s", utc=True)
        data.rename(columns={"tick_volume": "volume"}, inplace=True)
        columns = ["time", "open", "high", "low", "close", "volume"]
        if "spread" in data:
            data.rename(columns={"spread": "spread_points"}, inplace=True)
            columns.append("spread_points")
        return data[columns]
    
    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current tick (latest bid/ask/volume).
        
        Args:
            symbol (str): Trading pair
        
        Returns:
            dict: Current tick with bid, ask, last, volume, spread
            None: If request fails
        """
        try:
            if not self.health_check():
                return None
            
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.error(f"Failed to get tick for {symbol}: {mt5.last_error()}")
                return None
            
            info = {
                "symbol": symbol,
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "volume": tick.volume,
                "spread": tick.ask - tick.bid,
                "spread_points": round((tick.ask - tick.bid) / mt5.symbol_info(symbol).point),
                "time": datetime.fromtimestamp(tick.time),
            }
            
            logger.debug(f"✓ Tick retrieved: {symbol} Bid={tick.bid} Ask={tick.ask}")
            return info
            
        except Exception as e:
            logger.error(f"get_tick({symbol}) error: {str(e)}", exc_info=True)
            return None
    
    # =========================================================================
    # POSITIONS & ORDERS
    # =========================================================================
    
    def get_open_positions(self) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve all open positions.
        
        Returns:
            list: List of position dictionaries with details
            None: If request fails
        """
        try:
            if not self.health_check():
                return None
            
            positions = mt5.positions_get()
            if positions is None:
                logger.error(f"Failed to get positions: {mt5.last_error()}")
                return None
            
            result = []
            for pos in positions:
                result.append({
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "type": "BUY" if pos.type == 0 else "SELL",
                    "volume": pos.volume,
                    "open_price": pos.price_open,
                    "current_price": pos.price_current,
                    "profit": pos.profit,
                    "swap": getattr(pos, "swap", 0.0),
                    "commission": getattr(pos, "commission", 0.0),
                    "profit_pips": round((pos.price_current - pos.price_open) / 
                                       mt5.symbol_info(pos.symbol).point),
                    "open_time": datetime.fromtimestamp(pos.time),
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "comment": pos.comment,
                })
            
            logger.debug(f"✓ Retrieved {len(result)} open positions")
            return result
            
        except Exception as e:
            logger.error(f"get_open_positions() error: {str(e)}", exc_info=True)
            return None
    
    def get_order_history(self, days: int = 7) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve order history from the last N days.
        
        Args:
            days (int): Number of days of history to retrieve (default: 7)
        
        Returns:
            list: List of closed order/deal dictionaries
            None: If request fails
        """
        try:
            if not self.health_check():
                return None
            
            # Get deals from last N days
            utc_from = datetime.utcnow() - timedelta(days=days)
            utc_from_timestamp = int(utc_from.timestamp())
            
            deals = mt5.history_deals_get(utc_from_timestamp)
            if deals is None:
                logger.error(f"Failed to get order history: {mt5.last_error()}")
                return None
            
            result = []
            for deal in deals:
                result.append({
                    "ticket": deal.ticket,
                    "order": deal.order,
                    "symbol": deal.symbol,
                    "type": "BUY" if deal.type == 0 else "SELL",
                    "volume": deal.volume,
                    "price": deal.price,
                    "commission": deal.commission,
                    "profit": deal.profit,
                    "time": datetime.fromtimestamp(deal.time, tz=timezone.utc),
                    "comment": deal.comment,
                    "swap": getattr(deal, "swap", 0.0),
                    "fee": getattr(deal, "fee", 0.0),
                })
            
            logger.debug(f"✓ Retrieved {len(result)} deals from last {days} days")
            return result
            
        except Exception as e:
            logger.error(f"get_order_history({days}) error: {str(e)}", exc_info=True)
            return None


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_client = None

def get_client() -> MT5Client:
    """
    Get or create the MT5 client singleton.
    
    Returns:
        MT5Client: The global MT5 client instance
    """
    global _client
    if _client is None:
        _client = MT5Client()
        if not _client.connect():
            logger.error("Failed to establish MT5 connection on startup")
            _client = None
            raise ConnectionError("Cannot connect to MT5")
    return _client

def close_client() -> None:
    """Close the global MT5 client."""
    global _client
    if _client is not None:
        _client.disconnect()
        _client = None
