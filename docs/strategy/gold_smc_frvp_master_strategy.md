# Gold (XAU/USD) SMC + FRVP Master Strategy

Reverse-engineered from TradingView indicators (SMC Ultimate Pro, Volumized Order Blocks by Flux Charts), verified against dummy charts, and refined through live chart walkthroughs.

---

## 1. Timeframe Structure

| Zone | Timeframes | Role |
|---|---|---|
| Trend bias | 4H | Establishes overall bullish/bearish bias |
| Setup zone | 1H, 30min | Where FRVP + order block confluence is located |
| Sniper entry zone | 15min, 5min, 1min | Where the 5-candle confirmation and actual entry happen |

---

## 2. Component 1 — Market Structure Detection

**Layer 1 — Fractal Pivot Detection**
- Swing High at bar `i`: `high[i] > max(high[i-N:i])` AND `high[i] > max(high[i+1:i+N+1])`
- Swing Low: mirrored on `low[i]`
- Alternating sequence enforced — if two same-type pivots form before an opposite one, keep only the more extreme
- Suggested `N` per TF: D1=3-5, H4=4-6, H1=5-8, M15/M30=6-10 (tune against real data once live)

**Layer 2 — HH/LH/HL/LL Labeling**
- Compare each new pivot only to the immediately prior pivot of the *same type*
- HH if new high > last swing high, else LH. HL if new low > last swing low, else LL
- No ATR/percent filter — pure relative comparison

**Layer 3 — BOS/CHoCH State Machine (close-based only)**
- `trend_state` ∈ {bullish, bearish}
- Two simultaneous live reference lines at all times:
  - Bullish: last HH (BOS ref) + last HL (CHoCH ref)
  - Bearish: last LL (BOS ref) + last LH (CHoCH ref)
- Each bar: check crossings first, then update references from any new pivot
- Close beyond same-direction reference → BOS (trend continues, reference rolls forward)
- Close beyond opposite reference → CHoCH (trend flips; broken level becomes provisional same-direction ref, old same-direction ref becomes new opposite ref)
- `bos_done` flag prevents re-firing every bar after a break

**Layer 4 — Multi-Timeframe**
- Each TF runs the pipeline independently — no built-in MTF filtering
- 4H bias → 1H/30min structure → 15min/5min/1min entry layering is built on top, per Section 1

**Output event format:** `(bar_idx, 'BOS'/'CHoCH', trend_after, ref_price, ref_pivot_idx)`

---

## 3. Component 2 — Order Block Detection

Source logic: Flux Charts' "Volumized Order Blocks" (Pine Script), `useBody = false` hardcoded (always wick-to-wick).

**3a. Swing detection for OBs** (rolling window, not left/right fractal)
- At bar `i`: `ref_idx = i - swingLength`; compare `high[ref_idx]` / `low[ref_idx]` against the rolling window extremes
- State persists — only updates on a type transition (top ↔ bottom)
- Script default `swingLength = 10`

**3b. OB creation trigger (close-based)**
- Bullish OB: `close[i] > top.y AND NOT top.crossed`
- Bearish OB: `close[i] < bottom.y AND NOT bottom.crossed`
- `crossed` flag prevents re-triggering off the same pivot

**3c. Anchor candle selection**
- Scan every bar strictly between the swing pivot and the breakout bar (exclusive both ends)
- Bullish OB: bar with the **lowest low** in that range → box = that bar's full high/low
- Bearish OB: bar with the **highest high** in that range → box = that bar's full high/low
- Always wick-to-wick, never candle body

**3d. Volume figures**
- `obVolume = volume[breakout] + volume[1] + volume[2]`
- `obHighVolume = volume[breakout] + volume[1]`; `obLowVolume = volume[2]`
- `percentage = min(obHighVolume, obLowVolume) / max(...) * 100` — a volume imbalance ratio across the 3 breakout bars, not a quality score

**3e. ATR size filter**
- `obSize = top - bottom`; discard if `obSize > ATR(10, true-range) * 3.5` measured at the breakout bar

**3f. Invalidation lifecycle** — one-directional, three states: `active → breaker → removed`
- Stage 1 (active→breaker), depends on `obEndMethod`:
  - "Wick" (default): `low[i] < ob.bottom` (bullish) / `high[i] > ob.top` (bearish)
  - "Close": body-only breach instead of wick
  - Breaker zone stays on chart as a potential reversal zone
- Stage 2 (breaker→removed) — **always wick-based regardless of `obEndMethod`**:
  - `high[i] > ob.top` (bullish breaker) / `low[i] < ob.bottom` (bearish breaker)
  - Once removed, deleted from the tracked list permanently

**3g. Combine overlapping OBs**
- Geometric intersection test on (time × price) rectangles, same-direction OBs only; "open" OBs extend to the last bar for time calculation
- Any overlap (>0%) → merge: `top=max`, `bottom=min`, volumes summed, `start=min`, `breaker=OR`
- Runs iteratively until no more merges possible (handles chains of 3+)

**3h. Display cap**
- `zoneCount` setting caps rendered zones per side (One/Low/Medium/High = 1/3/5/10); sorted by most-recent first
- Older zones stay in the full tracked list, just excluded from the visible/rendered set

**Design decision:** `detect_order_blocks()` returns two layers:
- `all_tracked_obs` — full post-combine list, used for actual strategy logic (entries/SL/TP)
- `visible_obs` — top-N post-cap, used only for chart rendering/display

---

## 4. Component 3 — Fixed Range Volume Profile (FRVP)

**Anchoring rule**
- One profile box per completed structural leg — anchored between two consecutive opposite-type swing points (HL→HH for a bullish leg, LH→LL for a bearish leg)
- Once that leg breaks and a new leg completes, a new profile anchors on the new leg; the old profile's POC/VAL/VAH lines stay on the chart, projected forward flat as reactive levels
- Frequent overlap between legs' POC/VAL/VAH is normal and often shows as "PREV POC AND VAH" style confluence

**Retest confirmation — 5 candle-pattern scenarios**, applied identically at POC, VAL, or VAH (any of the three can independently qualify a setup):

*Bearish context (price broke the leg down, retraces up into the level):*
1. Bearish engulfing candle at the level → **short confirmed**
2. Bearish "3-candle engulfing" (engulfs the combined range of the prior 2 candles) → **short confirmed**, stronger variant
3. Ranging/choppy candles, no clear engulfing → **no trade**, wait for confirmation
4. Bullish engulfing candle closes above the level, and no candle within the next 3 candles closes back under it → **short invalidated**, flip bias — look for longs toward the nearest valid OB or the next level up
5. Bullish ranging/choppy, no clear engulfing → **both directions invalidated**, no trade

*Bullish context (VAH, or POC/VAH after breaking above) — exact mirror:*
1. Bullish engulfing at the level → **long confirmed**
2. Bullish 3-candle engulfing → **long confirmed**, stronger
3. Ranging, no engulfing → **no trade**
4. Bearish engulfing closes below the level, holds for 3 candles → **long invalidated**, flip to shorts toward POC/VAL or next OB
5. Bearish ranging, no engulfing → **no trade**, either direction

**A+ setup:** POC/VAL/VAH level coincides with a valid order block's price zone.

---

## 5. Master Strategy Sequence (6 steps)

1. **Find trend** (bullish/bearish) using the timeframe structure in Section 1.
2. **Find valid swing points** — bullish: HH, HL. Bearish: LH, LL.
3. **Draw FRVP** — bullish: anchor recent HL→HH. Bearish: anchor recent LH→LL.
4. **Locate VAH, POC, VAL** on that profile.
5. **Order block check:**
   - Any of POC, VAH, or VAL can qualify a setup on its own — doesn't have to be POC.
   - **Priority:** validate POC first. Only consider VAH or VAL if POC fails the 5-candle rule or lacks OB confluence. Whichever qualifying level price reaches and confirms *first* is the one traded — no stacking a second entry on the same leg.
   - If the level sits at, or close to, a valid order block → premium A+ setup zone.
   - Wait for the 5-candle rule to confirm whether the level holds.
   - **If it holds**, enter toward the next valid OB **on the same sniper-entry-zone timeframe** (15min/5min/1min) — not the setup zone:
     - Base case: TP = next valid OB on the entry-zone TF.
     - Hard filter: if that OB doesn't clear 1:3 minimum R:R from the swing-point SL, check the next OB further out on the same TF. If nothing clears 1:3, skip the trade — never shrink the SL to force the ratio.
     - If the TP-target OB flips active→breaker mid-trade: auto-retarget TP to the next valid OB on that TF (cascade forward), no action on the open position.
     - If the TP-target OB goes breaker→removed mid-trade: move SL to breakeven, let it ride to the new target rather than closing at market.
     - A+ case: the entry-zone OB also sits inside a setup-zone (1H/30min) OB.
     - Best case: a POC/VAL/VAH level also rests at that same confluence zone.
   - If no setup zone in sight → target the nearest valid swing point instead.
6. **Risk and lot size:**
   - Flat 10% risk per entry.
   - SL at the nearest valid swing point to the order block.
   - Lot size derived from SL distance to fit the 10% cap.
   - Lot size scales up as the account grows (per $100 gained), always capped at 10% of the *current* balance — never a fixed dollar figure.
   - **Circuit breaker:** stop trading for the rest of the day after 2 consecutive losses.

---

## 6. Open Items / Next Steps

- [ ] Port structure detection, OB pipeline, and FRVP scenario engine into a single production module set for `strategy_config.py`
- [ ] Tune fractal `N` and `swingLength` per timeframe against real historical data
- [ ] Backtest the flat 10% risk assumption against realistic SMC win-rate expectations
- [ ] Validate 1:3 R:R hit-rate from entry-zone-TF OBs specifically (Section 5, step 5) before relying on it as a hard filter
- [ ] Decide `obEndMethod` ("Wick" vs "Close") for production
