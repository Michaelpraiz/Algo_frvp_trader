# Backtesting, Optimization, and Review Data

## Running a baseline

`mt5-backtest` runs a chronological, single-position simulation on a selected symbol and
timeframe. The default date window is the preceding 730 days. Data can come from the
configured MT5 terminal or a CSV containing `time,open,high,low,close` and optional
`volume` or `tick_volume`. Timestamps without an offset are treated as UTC; rows are
sorted and duplicate timestamps retain the last row.

```powershell
$env:PYTHONPATH = "src"
.\venv\Scripts\python.exe -m mt5_mcp.backtesting --symbol GOLD# --timeframe M15
.\venv\Scripts\python.exe -m mt5_mcp.backtesting --symbol GOLD# --timeframe M15 --csv .\data\gold_m15.csv --output .\data\baseline.json
.\venv\Scripts\python.exe -m mt5_mcp.backtesting --symbol GOLD# --timeframe M15 --optimize --folds 3 --grid '{"minimum_rr":[2.5,3.0],"risk_percent":[1,2],"session_start_hour":[7,9],"session_end_hour":[16,21],"frvp_lookback_period":[50,100],"sl_buffer_points":[0,5]}'
```

To use the `mt5-backtest` console command instead, install the local project once with
`.\venv\Scripts\python.exe -m pip install -e .`.

`minimum_rr`, `risk_percent`, `session_start_hour`, `session_end_hour`,
`frvp_lookback_period`, `sl_buffer_points`, `swing_lookback`, `value_area_pct`, and
`tick_size` are tunable. The optimizer accepts JSON arrays for any subset of those fields,
limits a sweep to 500 combinations, and uses expanding chronological training windows
followed by non-overlapping out-of-sample windows. It reports each fold's training and
out-of-sample results. Its training rank is expectancy in R less a drawdown penalty above
20%; inspect sample counts and every out-of-sample fold before approving anything.

## Modeled strategy and simulation assumptions

- H4 bias is determined from confirmed higher-high/higher-low or lower-high/lower-low
  pivots. A pivot is unavailable until its right-side confirmation bars have closed.
- Candidate setup types are BOS with a liquidity sweep, a return to a deterministic
  order-block proxy, and an engulfing retest of the rolling FRVP POC/VAL/VAH. POC has
  priority when several profile levels are touched on one candle.
- The FRVP calculation uses tick volume distributed across the prior OHLC range. The
  current candle is excluded from its profile.
- Stops use the most recent causally confirmed opposing swing with a configurable buffer.
  Targets use the nearest already-confirmed opposing swing. Trades without a confirmed
  target or below the configured minimum R:R are skipped and logged.
- Risk is a fixed percentage of the evolving balance, capped at 3% per trade and 10 lots.
  Volume is rounded down to the broker step; entries are rejected if minimum volume,
  margin, or modeled costs would breach the risk cap. The configured maximum daily loss
  (measured against UTC day-start balance), two-consecutive-loss circuit breaker, and
  post-stop cooldown are applied. If both stop and target are inside one bar, the stop is
  assumed to have occurred first.
- MT5-loaded bars use their historical spread points. Missing spreads use the configured
  instrument fallback (GOLD#: 24 points); the default slippage is one point per fill,
  an explicit proxy because OHLC bars cannot reveal actual execution slippage. Commission
  is configured per symbol and per lot per side; the observed GOLD# deal history available
  during calibration had zero commission/fees, which is account-specific and not a broker
  guarantee. The simulator uses MT5 tick value, contract size, volume bounds/step, stop
  level, and current leverage as a historical margin approximation. Equity marking
  includes spread, slippage, and commission estimates.
- The cost model does not simulate partial exits, financing, correlated open positions,
  order-book depth, latency, or changing historical margin requirements. Validate all
  assumptions against current broker statements before using results operationally.

This is a **causal backtest adapter for the documented rules**, not a replay of
`TradeEngine.generate_trade_plan()`: that live planner evaluates current MT5 snapshots and
does not accept a historical point-in-time data provider. In particular, the backtest's
order-block detector is a reproducible proxy, not a validation of discretionary OB or
liquidity quality. Those criteria are captured as setup features for qualitative review,
not grid-optimized. Validate the entry and target model against charts and broker costs
before using its statistics for decisions.
For MT5-loaded candles, the broker's symbol point size is used for the stop-loss buffer.
For CSV data, supply `tick_size` in `--parameters` (or MCP `parameters_json`) to match the
instrument specification; otherwise the point size is inferred from price increments.

## Human approval and periodic review

1. Run `optimize_backtest`; it creates a `pending_approval` proposal, never edits
   `strategy_config.py` or live settings.
2. Inspect it with `list_optimizer_proposals`. To record the decision, call
   `approve_optimizer_proposal` with the proposal ID, `confirm=true`, and a human review
   note; or use `reject_optimizer_proposal`. An approval is stored separately as an
   approved parameter snapshot; applying it to live configuration is a separate manual
   change.
3. Import closed broker trades with `import_live_trade_log` using a CSV with at minimum
   `symbol`, `entry_time` (or `time`), and `pnl` (or `pnl_usd`/`profit`). Optional trade
   IDs/tickets, `side`, `setup_type`/`entry_reason`, `confluence_score`, and `rr_achieved`
   are retained where present. Duplicate external IDs fail rather than overwrite a prior
   log.
4. Export a bounded review/training bundle with `export_backtest_review_bundle`. It
   contains candidate setup features, rejection reasons, binary trade-outcome labels when
   available, backtest trade records, and imported live trade records. The bundle includes
   a qualitative prompt focused on order-block/liquidity failure patterns. It is a local
   export only: no third-party LLM is called and no code or account data is sent anywhere.

## Local logging schema

The ignored SQLite database `data/backtest_logs.sqlite3` stores:

| Table | Purpose |
|---|---|
| `backtest_runs` | Immutable date range, parameters, metrics, and methodology |
| `setup_logs` | Every generated candidate, setup type, features, filter status, and outcome label |
| `trade_logs` | Entry/exit, outcome, realized R, PnL, and balance snapshot |
| `optimization_runs` | Search identity and aggregated out-of-sample metrics |
| `optimizer_evaluations` | Per-fold parameter combinations and training scores |
| `optimizer_proposals` | Pending/approved/rejected recommendation and human decision note |
| `approved_parameters` | Versioned, explicitly approved parameter snapshot; not live config |
| `live_trade_logs` | Imported broker trades and any supplied setup labels/features |
| `review_exports` | Audit record of generated qualitative-review bundles |

Setup rows expose `outcome_label` (1 for win, 0 for loss, null where no completed label is
available) and a structured `features_json`; filtered-out candidates remain useful negative
examples. This makes a future supervised entry-filter dataset possible without treating
unexecuted candidates as known losses.
