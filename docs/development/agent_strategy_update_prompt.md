# Task: Update strategy_config.py and all dependent components to match the new master strategy

## Source of truth
`gold_smc_frvp_master_strategy.md` (in the project root) is now the authoritative trading strategy specification. It replaces and supersedes any prior strategy logic currently in this codebase — including the old top-down flow (D1 bias → H4 structure → H1/M15 entry) and the old risk schedule (5% default / 10% ceiling / 2.5% after 2 losses), wherever they still appear.

## Working style — read this before touching any file
- Work methodically. Do not write or modify any file until I've explicitly approved the change.
- Batch your findings: give me a full audit first, then wait for my go-ahead, then apply everything I approve in one pass — don't drip-feed individual edits for approval one at a time.
- `strategy_config.py` drives Python code logic; `STRATEGY_SYSTEM_PROMPT` (or equivalent AI-reasoning prompt string) drives AI reasoning. Both must exist and stay in sync — don't collapse one into the other or drop either.
- Any SMC/ICT session time logic must account for DST and be expressed in both UTC and WAT (UTC+1).

## Phase 1 — Audit (read-only, no edits yet)
1. Read `gold_smc_frvp_master_strategy.md` in full.
2. Read the current `strategy_config.py` and every module in this project that implements or references: market structure detection, order block detection, volume profile / FRVP, entry logic, stop-loss/take-profit logic, lot sizing, risk management, or timeframe configuration.
3. Search the whole codebase (not just strategy_config.py) for anything tied to the old logic, including but not limited to:
   - Old timeframe roles (D1 bias / H4 structure / H1-M15 entry) — should become 4H bias / 1H-30min setup / 15min-5min-1min sniper entry
   - Outdated per-trade risk or loss-streak rules — current policy is at most 3% risk per trade, a 10% UTC daily loss limit, and no consecutive-loss halt
   - Any TP logic not yet aligned to: TP = next valid OB on the *same* entry-zone timeframe, 1:1–1:29.44 net R:R bounds (never shrink SL to force a ratio), cascading retarget on OB breaker, breakeven-and-hold on OB removal
   - Any SL logic not yet aligned to: nearest valid swing point to the order block
   - Missing or incomplete implementations of: the market structure BOS/CHoCH state machine, the full order block pipeline (swing detection → trigger → anchor selection → ATR filter → invalidation lifecycle → combine → display cap, returning both `all_tracked_obs` and `visible_obs`), and the FRVP anchoring + 5-candle retest scenario engine (POC/VAL/VAH, with POC validated first per the master strategy's priority rule)
4. Produce a structured report: for each affected file, list what's missing, what's wrong/outdated, and what needs to be added — no code changes yet.

## Phase 2 — Wait for approval
Present the Phase 1 report to me. Do not proceed to Phase 3 until I explicitly approve which items to apply.

## Phase 3 — Apply
Once approved, implement the changes across all affected files in one coordinated pass, keeping `strategy_config.py` and the AI-reasoning prompt string in sync with each other and with the master strategy document.

## Phase 4 — Verify
After changes are applied, re-scan the codebase to confirm no file still references the old timeframe flow, old risk schedule, or any other superseded logic. Report anything left unresolved.
