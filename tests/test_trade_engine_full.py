#!/usr/bin/env python
"""Full Trade Engine test suite with logging."""

import sys
import logging

# Setup logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='test_trade_engine_full.log'
)

logger = logging.getLogger(__name__)

def main():
    logger.info("="*80)
    logger.info("TRADE ENGINE - FULL TEST SUITE (ALL 9 FUNCTIONS)")
    logger.info("="*80)
    
    try:
        from mt5_mcp.trade_engine import get_trade_engine
        engine = get_trade_engine()
        logger.info("[OK] Trade Engine loaded\n")
        
        symbol = "EURUSD"
        
        # Test 1: HTF Bias
        logger.info("-"*80)
        logger.info("TEST 1: get_htf_bias()")
        logger.info("-"*80)
        bias = engine.get_htf_bias(symbol)
        logger.info(f"Result: {bias}\n")
        
        # Test 2: BOS/CHoCH
        logger.info("-"*80)
        logger.info("TEST 2: detect_bos_choch()")
        logger.info("-"*80)
        bos = engine.detect_bos_choch(symbol, "H4")
        logger.info(f"Result: {bos}\n")
        
        # Test 3: Order Blocks
        logger.info("-"*80)
        logger.info("TEST 3: find_order_blocks()")
        logger.info("-"*80)
        obs = engine.find_order_blocks(symbol, "H4")
        logger.info(f"Valid OBs: {obs['valid_count']}")
        logger.info(f"Result: {obs}\n")
        
        # Test 4: FVGs
        logger.info("-"*80)
        logger.info("TEST 4: find_fvg()")
        logger.info("-"*80)
        fvgs = engine.find_fvg(symbol, "H4")
        logger.info(f"Valid FVGs: {fvgs['valid_count']}")
        logger.info(f"Result: {fvgs}\n")
        
        # Test 5: Liquidity Levels
        logger.info("-"*80)
        logger.info("TEST 5: find_liquidity_levels()")
        logger.info("-"*80)
        liq = engine.find_liquidity_levels(symbol, "H4")
        logger.info(f"PDH: {liq['pdh']:.5f}, PDL: {liq['pdl']:.5f}")
        logger.info(f"Result: {liq}\n")
        
        # Test 6: Liquidity Sweep
        logger.info("-"*80)
        logger.info("TEST 6: check_liquidity_sweep()")
        logger.info("-"*80)
        sweep = engine.check_liquidity_sweep(symbol, "H1")
        logger.info(f"Sweep detected: {sweep['sweep_detected']}")
        logger.info(f"Result: {sweep}\n")
        
        # Test 7: Premium/Discount
        logger.info("-"*80)
        logger.info("TEST 7: check_premium_discount()")
        logger.info("-"*80)
        ote = engine.check_premium_discount(symbol)
        logger.info(f"Zone: {ote['zone_type']}")
        logger.info(f"Result: {ote}\n")
        
        # Test 8: Confluence Scoring
        logger.info("-"*80)
        logger.info("TEST 8: score_setup()")
        logger.info("-"*80)
        score = engine.score_setup(symbol)
        logger.info(f"Confluence Score: {score['confluence_score']}/100")
        logger.info(f"Recommendation: {score['recommendation']}")
        logger.info(f"Result: {score}\n")

        # Phase 4.2-4.4 regression checks
        assert 'quality_score' in obs, "Order block scanner should expose quality_score"
        assert isinstance(obs['quality_score'], (int, float)), "Order block quality should be numeric"
        assert 'quality_score' in fvgs, "FVG detector should expose quality_score"
        assert isinstance(fvgs['quality_score'], (int, float)), "FVG quality should be numeric"
        assert 'weights' in score, "Confluence scoring should expose weighted contributions"
        assert 'ob_quality' in score['score_breakdown'] or 'fvg_quality' in score['score_breakdown'], "Score breakdown should include OB/FVG quality contributions"
        
        # Test 9: Complete Trade Plan
        logger.info("-"*80)
        logger.info("TEST 9: generate_trade_plan()")
        logger.info("-"*80)
        plan = engine.generate_trade_plan(symbol)
        logger.info(f"Recommendation: {plan.get('recommendation', 'N/A')}")
        if 'trade_plan' in plan:
            logger.info(f"Entry: {plan['trade_plan'].get('entry', 'N/A')}")
            logger.info(f"SL: {plan['trade_plan'].get('stop_loss', 'N/A')}")
            logger.info(f"TP: {plan['trade_plan'].get('take_profit', 'N/A')}")
        logger.info(f"Result: {plan}\n")
        
        logger.info("="*80)
        logger.info("ALL 9 TESTS COMPLETED SUCCESSFULLY")
        logger.info("="*80)
        print("Full test completed - check test_trade_engine_full.log")
        
    except Exception as e:
        logger.exception(f"[ERROR] {type(e).__name__}: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
