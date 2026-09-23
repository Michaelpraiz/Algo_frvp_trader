# FRVP (Fixed Range Volume Profile) — Implementation Spec for `frvp.py`

Target: MT5 MCP server, Python, `MetaTrader5` pip package. This spec adapts TradingView's
FRVP calculation to MT5's available data (OHLCV bars + `tick_volume`, no native volume
profile API) and combines it with Mac's confirmed anchoring/retest rules.

---

## 1. Purpose

Given a structural leg (swing-to-swing range) from the market structure engine, compute a
volume profile over that range and return `POC`, `VAL`, `VAH`. These feed directly into the
entry logic already spec'd in `frvp-component.md` (engulfing confirmation at POC/VAL/VAH).

---

## 2. Inputs

```python
def compute_frvp(
    symbol: str,
    anchor_time: datetime,      # start of leg (older swing point)
    end_time: datetime,         # end of leg (newer swing point, i.e. leg break)
    value_area_pct: float = 0.70,   # % of total volume enclosed by VAL-VAH
    max_bars: int = 5000,           # TradingView's bar-count ceiling
    row_mode: str = "ticks_per_row",  # "ticks_per_row" | "num_rows"
    row_size: float = 10,             # ticks per row, or number of rows depending on row_mode
) -> FRVPResult:
```

```python
@dataclass
class FRVPResult:
    poc: float
    val: float
    vah: float
    profile: dict[float, float]   # price_bin -> volume, for debugging/plotting
    timeframe_used: str           # which MT5 timeframe the calc fell back to
    total_volume: float
```

---

## 3. Timeframe selection (cascade rule)

MT5 timeframes to check in order, mirroring TradingView's sequence:

```
M1 -> M5 -> M15 -> M30 -> H1 -> H4 -> D1
```

Algorithm:
1. For each timeframe in the sequence, call `mt5.copy_rates_range(symbol, tf, anchor_time, end_time)`.
2. Count bars returned. If `bar_count < max_bars`, use this timeframe — stop.
3. If every timeframe up to D1 still exceeds `max_bars` (only realistic on very long anchor
   ranges), fall back to D1 regardless of count.
4. If a lower timeframe has no data that far back (`copy_rates_range` returns empty/None while
   the anchor range clearly has price action), fall back to the chart's own timeframe
   (i.e. whatever timeframe the structure engine used to detect the swing points).
5. **MT5-specific deviation from TradingView**: no sub-M1 data is available via the standard
   API. Skip the "1S" fallback — if the anchor range is shorter than one M1 bar span in bars,
   just use M1.

Record `timeframe_used` in the result for debugging/backtesting.

---

## 4. Volume source

- MT5 (and XM specifically, as a market-maker broker) does not provide true traded volume —
  only `tick_volume` (number of price changes/ticks per bar).
- Use `tick_volume` as the volume proxy for every calculation below. This is the standard
  and accepted workaround; do not attempt to source real volume externally for this project.

---

## 5. Binning (row layout)

Given the anchor range's high (`range_high`) and low (`range_low`) across all fetched bars:

- Get `tick_size` via `mt5.symbol_info(symbol).point`.
- **`row_mode = "ticks_per_row"`**: `bin_width = row_size * tick_size`. Number of bins =
  `ceil((range_high - range_low) / bin_width)`.
- **`row_mode = "num_rows"`**: `raw_ticks_per_row = (range_high - range_low) / row_size / tick_size`.
  Round `raw_ticks_per_row` to the nearest integer ticks-per-row value that makes the
  resulting row count closest to `row_size` (test round-up and round-down, pick whichever
  total row count is closer to the requested `row_size`; on a tie, prefer more rows).
  `bin_width = ticks_per_row * tick_size`.
- Default to `ticks_per_row` mode with `row_size=10` unless a specific instrument needs
  tuning (very low-priced/high tick-count symbols may want `num_rows` instead).

---

## 6. Volume distribution per bar

For each bar in the fetched range:

1. Determine the bar's price span: `[bar_low, bar_high]`.
2. Find every bin the bar's span overlaps.
3. Distribute the bar's `tick_volume` across those bins **proportionally to the fraction of
   the bar's range each bin overlaps**:
   ```
   overlap_fraction(bin) = overlap(bin_range, [bar_low, bar_high]) / (bar_high - bar_low)
   bin_volume += tick_volume * overlap_fraction(bin)
   ```
   (If `bar_high == bar_low`, i.e. a doji/flat bar, assign 100% of volume to the single bin
   containing that price.)
4. Up/down split (only needed if a future feature wants delta view — not required for
   POC/VAL/VAH, skip unless requested): classify the bar as up if `close > open`, down if
   `close <= open`, per TradingView's rule.

---

## 7. POC / VAL / VAH calculation

1. `total_volume = sum(all bin volumes)`.
2. `POC` = midpoint price of the bin with the maximum volume. On a tie, pick the bin closest
   to the middle of the range (or the higher-priced bin — pick one convention and stay
   consistent).
3. **Value area expansion** (standard algorithm, mirrors TradingView's "value area volume %"):
   - Start with `enclosed_volume = POC_bin_volume`, `low_idx = high_idx = POC_bin_index`.
   - Loop: compare the volume of the next bin below `low_idx` vs the next bin above
     `high_idx`. Add whichever is greater to `enclosed_volume` and expand that boundary
     outward (on a tie, add both, or alternate — pick one convention and document it in code).
   - Stop when `enclosed_volume >= value_area_pct * total_volume` or both boundaries hit the
     edge of the profile.
   - `VAL` = bottom price of the lowest included bin, `VAH` = top price of the highest
     included bin.

---

## 8. Anchoring / re-anchor behavior (already confirmed, restated for the implementer)

- One FRVP profile per structural leg: anchored between two consecutive opposite-type swing
  points (HL→HH or LH→LL) — same swing points the structure engine already detects.
- When the current leg breaks and a new leg completes, anchor a new profile on the new leg.
- The old profile's POC/VAL/VAH are **not discarded** — extend them forward as flat
  reference lines (mirrors TradingView's "extend right" behavior) for retest detection even
  after a new profile has been anchored.
- Maintain a list/stack of past profiles (or at minimum their POC/VAL/VAH + validity window)
  so the entry-logic module can check retests against any still-relevant prior level, not
  just the current leg's profile.

---

## 9. Integration points

- **Trigger**: call `compute_frvp()` on the same "leg break / new leg confirmed" event the
  structure engine already fires — do not re-poll on every tick/bar.
- **Consumer**: the entry-confirmation logic in `frvp-component.md` (engulfing-candle
  scenarios at POC/VAL/VAH) reads `FRVPResult.poc/.val/.vah` plus the extended-forward levels
  from prior legs.
- **A+ setup flag**: after computing a profile, check `poc`/`val`/`vah` against the order
  block module's output for the same leg — if a level falls inside a valid OB's price zone,
  tag it as FRVP+OB confluence per the existing rule.

---

## 10. Edge cases

- Anchor range shorter than one bar on the smallest available timeframe → use M1, single-bar
  profile (POC=VAL=VAH= that bar's typical price, or just its close).
- Symbol with very large tick size relative to range (e.g. low-volatility instrument) →
  guard against `bin_count < 3`; force `num_rows` mode with a sane minimum (e.g. 10 rows) if
  `ticks_per_row` mode would produce too few bins.
- Gaps/holidays inside the anchor range → `copy_rates_range` already skips non-trading time,
  no special handling needed.
- No bars returned at all (bad symbol/time range) → raise/return an explicit error, do not
  silently return an empty profile.

---

## 11. Not required for v1

- Up/down volume split or delta view (TradingView feature, not used by the current entry
  logic — only POC/VAL/VAH matter for the confirmed retest scenarios).
- Session-based (rather than leg-based) anchoring.
