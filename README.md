# MT5 MCP Trading Server

A Python MCP server for MetaTrader 5 market data, SMC structure analysis, risk checks, and fixed-range volume profile (FRVP) analysis.

## Strategy Flow

The Gold SMC + FRVP strategy uses:

- H4 for directional bias
- H1 and M30 for structure, order-block, and FRVP setup zones
- M15, M5, and M1 for entry confirmation
- Tick volume as the MT5 volume-profile proxy

The server does not place trades unless an order tool is explicitly called with its required confirmation.

## Setup

1. Install Python 3.11 or newer and MetaTrader 5.
2. Create an environment and install dependencies:

   ```powershell
   python -m venv venv
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set `MT5_PROFILE=demo` or `MT5_PROFILE=live`.
4. Copy `.env.demo.example` to `.env.demo` and `.env.live.example` to `.env.live`, then fill in the appropriate local credentials.
5. Open the workspace in VS Code. The MCP server is configured in `.vscode/mcp.json`.

## Run Checks

With `PYTHONPATH=src` configured:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

## Backtesting and Optimization

Run a two-year MT5 history backtest (the default range), or point it at an OHLCV
CSV with `time,open,high,low,close` and optional `volume`/`tick_volume` columns:

```powershell
$env:PYTHONPATH = "src"
.\venv\Scripts\python.exe -m mt5_mcp.backtesting --symbol GOLD# --timeframe M15
.\venv\Scripts\python.exe -m mt5_mcp.backtesting --symbol GOLD# --timeframe M15 --csv .\data\gold_m15.csv
.\venv\Scripts\python.exe -m mt5_mcp.backtesting --symbol GOLD# --timeframe M15 --optimize --folds 3
```

Alternatively, install the project in editable mode once to use the `mt5-backtest`
console command without setting `PYTHONPATH`:

```powershell
.\venv\Scripts\python.exe -m pip install -e .
mt5-backtest --symbol GOLD# --timeframe M15
```

The MCP server also exposes `run_backtest`, `optimize_backtest`,
`list_optimizer_proposals`, `approve_optimizer_proposal`, `reject_optimizer_proposal`,
`import_live_trade_log`, and `export_backtest_review_bundle`. Backtest runs, setup
features/labels, trade outcomes, optimizer evaluations, and human decisions are stored
locally in `data/backtest_logs.sqlite3` (ignored by Git). Optimizer results are proposals;
approval records an explicit human decision and **does not edit live strategy settings**.
Export a review bundle periodically for qualitative LLM review or later supervised-model
experiments. No LLM is invoked automatically.

See [docs/backtesting.md](docs/backtesting.md) for the modeled rules, parameters,
limitations, MCP examples, and log schema.

The server entry point is:

```text
mt5_mcp.server
```

The server requires the MCP SDK installed from `requirements.txt` and exits
with an error if the SDK cannot be loaded; it does not provide a non-MCP
stdio fallback.

## Layout

```text
src/mt5_mcp/       application package and MCP tools
tests/             automated and integration checks
scripts/           operational utilities
docs/              strategy and development documentation
logs/              local runtime logs, ignored by Git
data/              local runtime data, ignored by Git
```

## Safety

Never commit `.env`, account credentials, runtime logs, SQLite databases, or temporary order scripts. Use a demo account while validating broker connectivity and strategy behavior.

To switch profiles, change only this selector in `.env`:

```env
MT5_PROFILE=demo
```

Use `MT5_PROFILE=live` only after filling `.env.live` and completing live-account checks. The application rejects an invalid profile or a profile whose `ACCOUNT_TYPE` does not match.
