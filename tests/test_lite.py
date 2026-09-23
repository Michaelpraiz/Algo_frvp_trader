"""
Phase 2.2 — MT5 Connection Test (Lightweight)
No pandas/numpy dependencies - pure MT5 API
"""

import sys
import logging
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - TEST - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

print("\n" + "="*70)
print("PHASE 2.2 — MT5 CONNECTION TEST (LIGHTWEIGHT)")
print("="*70)

# Test 1: Check credentials
print("\n" + "="*70)
print("TEST 1: CONFIGURATION")
print("="*70)

login = os.getenv("MT5_LOGIN")
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")
account_type = os.getenv("ACCOUNT_TYPE", "demo")

if not all([login, password, server]):
    logger.error("✗ Missing MT5 credentials in .env")
    sys.exit(1)

logger.info("✓ Credentials loaded:")
logger.info(f"  Account: {login}")
logger.info(f"  Server: {server}")
logger.info(f"  Type: {account_type}")

# Test 2: Import MT5
print("\n" + "="*70)
print("TEST 2: IMPORT METATRADER5")
print("="*70)

try:
    import MetaTrader5 as mt5
    logger.info("✓ MetaTrader5 module imported")
except ImportError as e:
    logger.error(f"✗ Failed to import MT5: {e}")
    sys.exit(1)

# Test 3: Initialize MT5
print("\n" + "="*70)
print("TEST 3: MT5 INITIALIZATION")
print("="*70)

try:
    logger.info("Initializing MT5...")
    if not mt5.initialize():
        error = mt5.last_error()
        logger.error(f"✗ MT5 initialization failed: {error}")
        logger.error("\n⚠️  TROUBLESHOOTING:")
        logger.error("  1. MetaTrader 5 terminal must be RUNNING")
        logger.error("  2. You must be LOGGED IN to demo account")
        logger.error("  3. Try: Start -> Find 'MetaTrader 5' -> Open")
        sys.exit(1)
    
    logger.info("✓ MT5 initialized successfully")
    
except Exception as e:
    logger.error(f"✗ Error: {e}")
    sys.exit(1)

# Test 4: Login
print("\n" + "="*70)
print("TEST 4: ACCOUNT LOGIN")
print("="*70)

try:
    logger.info(f"Attempting login: {login}@{server}...")
    if not mt5.login(login=int(login), password=password, server=server):
        error = mt5.last_error()
        logger.error(f"✗ Login failed: {error}")
        mt5.shutdown()
        sys.exit(1)
    
    logger.info("✓ Login successful")
    
except Exception as e:
    logger.error(f"✗ Error during login: {e}")
    mt5.shutdown()
    sys.exit(1)

# Test 5: Account Info
print("\n" + "="*70)
print("TEST 5: ACCOUNT INFORMATION")
print("="*70)

try:
    account = mt5.account_info()
    if account is None:
        logger.error("✗ Failed to retrieve account info")
        mt5.shutdown()
        sys.exit(1)
    
    logger.info("✓ Account info retrieved:")
    logger.info(f"  Name: {account.name}")
    logger.info(f"  Balance: ${account.balance:.2f}")
    logger.info(f"  Equity: ${account.equity:.2f}")
    logger.info(f"  Free Margin: ${account.margin_free:.2f}")
    logger.info(f"  Margin Level: {account.margin_level:.2f}%")
    logger.info(f"  Leverage: 1:{account.leverage}")
    
except Exception as e:
    logger.error(f"✗ Error: {e}")
    mt5.shutdown()
    sys.exit(1)

# Test 6: Symbol Info
print("\n" + "="*70)
print("TEST 6: EURUSD SYMBOL INFO")
print("="*70)

try:
    sym = mt5.symbol_info("EURUSD")
    if sym is None:
        logger.error("✗ Symbol EURUSD not found")
        mt5.shutdown()
        sys.exit(1)
    
    logger.info("✓ EURUSD info retrieved:")
    logger.info(f"  Bid: {sym.bid:.5f}")
    logger.info(f"  Ask: {sym.ask:.5f}")
    logger.info(f"  Spread: {sym.spread} points")
    logger.info(f"  Digits: {sym.digits}")
    logger.info(f"  Contract Size: {sym.trade_contract_size}")
    
except Exception as e:
    logger.error(f"✗ Error: {e}")
    mt5.shutdown()
    sys.exit(1)

# Test 7: Get Candles
print("\n" + "="*70)
print("TEST 7: EURUSD H1 CANDLES (last 5)")
print("="*70)

try:
    candles = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_H1, 0, 5)
    if candles is None:
        logger.error("✗ Failed to get candles")
        mt5.shutdown()
        sys.exit(1)
    
    logger.info(f"✓ Retrieved {len(candles)} candles:")
    logger.info("\n  Time           | Open   | High   | Low    | Close  | Volume")
    logger.info("  " + "-" * 65)
    
    for candle in candles:
        time = datetime.fromtimestamp(candle[0])
        logger.info(f"  {time.strftime('%Y-%m-%d %H:%M')} | {candle[1]:.5f} | {candle[2]:.5f} | {candle[3]:.5f} | {candle[4]:.5f} | {candle[5]:.0f}")
    
except Exception as e:
    logger.error(f"✗ Error: {e}")
    mt5.shutdown()
    sys.exit(1)

# Test 8: Get Tick
print("\n" + "="*70)
print("TEST 8: CURRENT TICK")
print("="*70)

try:
    tick = mt5.symbol_info_tick("EURUSD")
    if tick is None:
        logger.error("✗ Failed to get tick")
        mt5.shutdown()
        sys.exit(1)
    
    logger.info("✓ Current tick retrieved:")
    logger.info(f"  Bid: {tick.bid:.5f}")
    logger.info(f"  Ask: {tick.ask:.5f}")
    logger.info(f"  Volume: {tick.volume}")
    logger.info(f"  Time: {datetime.fromtimestamp(tick.time)}")
    
except Exception as e:
    logger.error(f"✗ Error: {e}")
    mt5.shutdown()
    sys.exit(1)

# Test 9: Get Positions
print("\n" + "="*70)
print("TEST 9: OPEN POSITIONS")
print("="*70)

try:
    positions = mt5.positions_get()
    if positions is None:
        logger.error("✗ Failed to get positions")
        mt5.shutdown()
        sys.exit(1)
    
    if len(positions) == 0:
        logger.info("✓ No open positions (expected on demo account)")
    else:
        logger.info(f"✓ Found {len(positions)} open positions:")
        for pos in positions:
            logger.info(f"  Ticket: {pos.ticket} | {pos.symbol} | Type: {'BUY' if pos.type == 0 else 'SELL'} | Volume: {pos.volume} | Profit: ${pos.profit:.2f}")
    
except Exception as e:
    logger.error(f"✗ Error: {e}")
    mt5.shutdown()
    sys.exit(1)

# Test 10: Get Orders
print("\n" + "="*70)
print("TEST 10: ORDER HISTORY (7 days)")
print("="*70)

try:
    utc_from = datetime.utcnow() - timedelta(days=7)
    utc_to = datetime.utcnow()
    
    # Try to get deals between timestamps
    deals = mt5.history_deals_get(int(utc_from.timestamp()), int(utc_to.timestamp()))
    
    if deals is None or len(deals) == 0:
        # This is normal for new accounts - not an error
        logger.info("✓ No deals in order history (expected on new account)")
    else:
        logger.info(f"✓ Found {len(deals)} deals:")
        for deal in deals[:5]:
            logger.info(f"  {datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M')} | {deal.symbol} | {'BUY' if deal.type == 0 else 'SELL'} | Profit: ${deal.profit:.2f}")
        
        if len(deals) > 5:
            logger.info(f"  ... and {len(deals) - 5} more")
    
except Exception as e:
    logger.error(f"✗ Error: {e}")
    mt5.shutdown()
    sys.exit(1)

# Cleanup
mt5.shutdown()
logger.info("MT5 connection closed")

# Summary
print("\n" + "="*70)
print("✓✓✓ ALL TESTS PASSED ✓✓✓")
print("="*70)
print("\n🎉 Phase 2.2 — MT5 Connection Layer is READY!\n")

sys.exit(0)
