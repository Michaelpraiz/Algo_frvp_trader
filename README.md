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
