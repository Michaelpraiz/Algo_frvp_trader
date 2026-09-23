#!/usr/bin/env python
"""Simple test script to validate trade_engine import and initialization."""

import sys
import logging

# Setup logging to file
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='test_trade_engine.log'
)

logger = logging.getLogger(__name__)

def main():
    logger.info("="*80)
    logger.info("TRADE ENGINE IMPORT TEST")
    logger.info("="*80)
    
    try:
        logger.info("Attempting to import trade_engine module...")
        from mt5_mcp.trade_engine import get_trade_engine
        logger.info("[OK] Module imported successfully")
        
        logger.info("Creating Trade Engine instance...")
        engine = get_trade_engine()
        logger.info("[OK] Trade Engine instance created")
        
        # Test one function
        logger.info("Testing get_htf_bias('EURUSD')...")
        result = engine.get_htf_bias('EURUSD')
        logger.info(f"[OK] Result: {result}")
        
        logger.info("\n" + "="*80)
        logger.info("ALL TESTS PASSED")
        logger.info("="*80)
        
        # Print to console as well
        print("Test completed - check test_trade_engine.log for details")
        
    except Exception as e:
        logger.exception(f"[ERROR] {type(e).__name__}: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
