"""Durable SQLite logging for backtests, setup labels, and optimizer approvals."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping
from uuid import uuid4

from .backtesting import _json_default

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "backtest_logs.sqlite3"


def _json(value: Any) -> str:
    return json.dumps(value, default=_json_default, allow_nan=False, sort_keys=True)


class BacktestStore:
    """Stores immutable run inputs/results and explicit optimizer approval actions."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path) if database_path else DEFAULT_DATABASE
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    bars INTEGER NOT NULL,
                    parameters_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    methodology_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS setup_logs (
                    setup_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES backtest_runs(run_id),
                    setup_time TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    setup_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rejection_reason TEXT,
                    outcome_label INTEGER,
                    features_json TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_setup_logs_type_time
                    ON setup_logs(setup_type, setup_time);
                CREATE INDEX IF NOT EXISTS idx_setup_logs_label
                    ON setup_logs(outcome_label);
                CREATE TABLE IF NOT EXISTS trade_logs (
                    trade_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES backtest_runs(run_id),
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    setup_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    result_r REAL NOT NULL,
                    pnl REAL NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS optimization_runs (
                    optimization_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    folds INTEGER NOT NULL,
                    grid_combinations INTEGER NOT NULL,
                    out_of_sample_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS optimizer_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    optimization_id TEXT NOT NULL REFERENCES optimization_runs(optimization_id),
                    fold INTEGER NOT NULL,
                    parameters_json TEXT NOT NULL,
                    training_metrics_json TEXT NOT NULL,
                    training_score REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS optimizer_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    optimization_id TEXT NOT NULL REFERENCES optimization_runs(optimization_id),
                    created_at TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending_approval','approved','rejected')),
                    decision_at TEXT,
                    decision_note TEXT
                );
                CREATE TABLE IF NOT EXISTS approved_parameters (
                    approval_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL UNIQUE REFERENCES optimizer_proposals(proposal_id),
                    approved_at TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    approval_note TEXT
                );
                CREATE TABLE IF NOT EXISTS live_trade_logs (
                    live_trade_id TEXT PRIMARY KEY,
                    imported_at TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    pnl REAL NOT NULL,
                    outcome_label INTEGER NOT NULL,
                    features_json TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_exports (
                    export_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    run_id TEXT,
                    setup_count INTEGER NOT NULL,
                    live_trade_count INTEGER NOT NULL
                );
            """)

    def save_backtest(self, result: Mapping[str, Any]) -> str:
        run_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                """INSERT INTO backtest_runs
                   (run_id,created_at,symbol,timeframe,start_time,end_time,bars,
                    parameters_json,metrics_json,methodology_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (run_id, _now(), result["symbol"], result["timeframe"], result["start_time"],
                 result["end_time"], result["bars"], _json(result["parameters"]),
                 _json(result["metrics"]), _json(result["methodology"])),
            )
            labels = {
                (trade["entry_time"], trade["setup_type"]): int(trade["outcome"] == "win")
                for trade in result["trades"]
            }
            for setup in result["setups"]:
                setup_id = str(uuid4())
                label = labels.get((setup.get("entry_time", setup["setup_time"]), setup["setup_type"]))
                db.execute(
                    """INSERT INTO setup_logs
                       (setup_id,run_id,setup_time,symbol,timeframe,setup_type,direction,
                        status,rejection_reason,outcome_label,features_json,record_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (setup_id, run_id, setup["setup_time"], setup["symbol"], setup["timeframe"],
                     setup["setup_type"], setup["direction"], setup["status"],
                     setup.get("rejection_reason"), label, _json(setup.get("features", {})), _json(setup)),
                )
            for trade in result["trades"]:
                db.execute(
                    """INSERT INTO trade_logs
                       (trade_id,run_id,entry_time,exit_time,setup_type,outcome,result_r,pnl,record_json)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (str(uuid4()), run_id, trade["entry_time"], trade["exit_time"], trade["setup_type"],
                     trade["outcome"], trade["result_r"], trade["pnl"], _json(trade)),
                )
        return run_id

    def save_optimization(self, result: Mapping[str, Any]) -> str:
        optimization_id = str(uuid4())
        proposal_id = str(uuid4())
        created_at = _now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO optimization_runs
                   (optimization_id,created_at,symbol,timeframe,folds,grid_combinations,out_of_sample_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (optimization_id, created_at, result["symbol"], result["timeframe"],
                 len(result["folds"]), result["grid_combinations"], _json(result["out_of_sample_average"])),
            )
            for evaluation in result["evaluations"]:
                db.execute(
                    """INSERT INTO optimizer_evaluations
                       (evaluation_id,optimization_id,fold,parameters_json,training_metrics_json,training_score)
                       VALUES (?,?,?,?,?,?)""",
                    (str(uuid4()), optimization_id, evaluation["fold"], _json(evaluation["parameters"]),
                     _json(evaluation["training_metrics"]), evaluation["training_score"]),
                )
            db.execute(
                """INSERT INTO optimizer_proposals
                   (proposal_id,optimization_id,created_at,parameters_json,validation_json,status)
                   VALUES (?,?,?,?,?,'pending_approval')""",
                (proposal_id, optimization_id, created_at, _json(result["proposal"]["parameters"]),
                 _json({"folds": result["folds"],
                        "out_of_sample_average": result["out_of_sample_average"],
                        "positive_out_of_sample_expectancy":
                            result["proposal"]["positive_out_of_sample_expectancy"]})),
            )
        return proposal_id

    def get_proposals(self, include_decided: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM optimizer_proposals"
        if not include_decided:
            query += " WHERE status='pending_approval'"
        query += " ORDER BY created_at DESC"
        with self._connect() as db:
            rows = db.execute(query).fetchall()
        return [{**dict(row), "parameters": json.loads(row["parameters_json"]),
                 "validation": json.loads(row["validation_json"])} for row in rows]

    def decide_proposal(self, proposal_id: str, approve: bool, note: str = "") -> dict[str, Any]:
        status = "approved" if approve else "rejected"
        decision_time = _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM optimizer_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Optimizer proposal not found: {proposal_id}")
            if row["status"] != "pending_approval":
                raise ValueError(f"Proposal {proposal_id} has already been {row['status']}")
            db.execute(
                """UPDATE optimizer_proposals SET status=?,decision_at=?,decision_note=?
                   WHERE proposal_id=?""",
                (status, decision_time, note, proposal_id),
            )
            if approve:
                db.execute(
                    """INSERT INTO approved_parameters
                       (approval_id,proposal_id,approved_at,parameters_json,approval_note)
                       VALUES (?,?,?,?,?)""",
                    (str(uuid4()), proposal_id, decision_time, row["parameters_json"], note),
                )
        return {"proposal_id": proposal_id, "status": status,
                "parameters": json.loads(row["parameters_json"]),
                "live_config_changed": False}

    def import_live_csv(self, path: str | Path) -> dict[str, Any]:
        source = Path(path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Live trade CSV does not exist: {source}")
        imported = 0
        with source.open(newline="", encoding="utf-8-sig") as handle, self._connect() as db:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("Live trade CSV must have a header row")
            for line_number, record in enumerate(reader, start=2):
                normalized = {str(key).strip().lower(): value for key, value in record.items() if key}
                safe_record = {
                    key: value for key, value in normalized.items()
                    if not any(marker in key for marker in ("password", "passwd", "secret", "token", "credential"))
                    and key not in {"login", "account_number"}
                }
                symbol = normalized.get("symbol")
                side = normalized.get("side", normalized.get("type", "unknown"))
                entry_time = normalized.get("entry_time", normalized.get("time"))
                pnl_value = normalized.get("pnl", normalized.get("pnl_usd", normalized.get("profit")))
                if not symbol or not entry_time or pnl_value in (None, ""):
                    raise ValueError(
                        f"Live trade CSV row {line_number} needs symbol, entry_time/time, and pnl/profit"
                    )
                try:
                    pnl = float(pnl_value)
                    entry_time = _iso_utc(entry_time)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid time or PnL on live trade CSV row {line_number}") from exc
                external_id = normalized.get("trade_id", normalized.get("ticket", normalized.get("id")))
                live_trade_id = str(external_id) if external_id else hashlib.sha256(
                    f"{source.resolve()}:{line_number}:{symbol}:{entry_time}".encode()
                ).hexdigest()
                features = {
                    "setup_type": normalized.get("setup_type", normalized.get("entry_reason")),
                    "confluence_score": _optional_float(normalized.get("confluence_score")),
                    "rr_achieved": _optional_float(normalized.get("rr_achieved")),
                }
                db.execute(
                    """INSERT INTO live_trade_logs
                       (live_trade_id,imported_at,entry_time,symbol,side,pnl,outcome_label,
                        features_json,record_json) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (live_trade_id, _now(), entry_time, symbol, str(side), pnl, int(pnl > 0),
                     _json(features), _json(safe_record)),
                )
                imported += 1
        return {"imported": imported, "source": str(source.resolve())}

    def export_review_bundle(
        self, output_path: str | Path | None = None, run_id: str | None = None,
        include_live: bool = True, max_rows: int = 2_000,
    ) -> dict[str, Any]:
        if max_rows < 1 or max_rows > 50_000:
            raise ValueError("max_rows must be from 1 through 50000")
        with self._connect() as db:
            if run_id:
                run = db.execute("SELECT * FROM backtest_runs WHERE run_id=?", (run_id,)).fetchone()
                if run is None:
                    raise KeyError(f"Backtest run not found: {run_id}")
                setups = db.execute(
                    "SELECT * FROM setup_logs WHERE run_id=? ORDER BY setup_time LIMIT ?",
                    (run_id, max_rows),
                ).fetchall()
                trades = db.execute(
                    "SELECT * FROM trade_logs WHERE run_id=? ORDER BY entry_time LIMIT ?",
                    (run_id, max_rows),
                ).fetchall()
                run_data = {**dict(run), "parameters": json.loads(run["parameters_json"]),
                            "metrics": json.loads(run["metrics_json"]),
                            "methodology": json.loads(run["methodology_json"])}
            else:
                run_data = None
                setups = db.execute(
                    "SELECT * FROM setup_logs ORDER BY setup_time DESC LIMIT ?", (max_rows,)
                ).fetchall()
                trades = db.execute(
                    "SELECT * FROM trade_logs ORDER BY entry_time DESC LIMIT ?", (max_rows,)
                ).fetchall()
            live = db.execute(
                "SELECT * FROM live_trade_logs ORDER BY entry_time DESC LIMIT ?", (max_rows,)
            ).fetchall() if include_live else []
        path = Path(output_path).expanduser() if output_path else (
            PROJECT_ROOT / "data" / f"backtest_review_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "schema_version": 1, "created_at": _now(), "run": run_data,
            "setups": [_decode_record(row, "record_json") | {
                "outcome_label": row["outcome_label"], "features": json.loads(row["features_json"])
            } for row in setups],
            "trades": [_decode_record(row, "record_json") for row in trades],
            "live_trades": [_decode_record(row, "record_json") | {
                "outcome_label": row["outcome_label"], "features": json.loads(row["features_json"])
            } for row in live],
            "review_prompt": (
                "Identify recurring qualitative failure/success patterns in order-block and liquidity "
                "validity. Separate observations from hypotheses, cite sample counts, compare setup types, "
                "and do not recommend changing live parameters without human approval."
            ),
        }
        path.write_text(json.dumps(bundle, indent=2, default=_json_default, allow_nan=False), encoding="utf-8")
        export_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                """INSERT INTO review_exports
                   (export_id,created_at,output_path,run_id,setup_count,live_trade_count)
                   VALUES (?,?,?,?,?,?)""",
                (export_id, _now(), str(path.resolve()), run_id, len(setups), len(live)),
            )
        return {"export_id": export_id, "output_path": str(path.resolve()),
                "setup_count": len(setups), "trade_count": len(trades),
                "live_trade_count": len(live), "llm_invoked": False}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _decode_record(row: sqlite3.Row, field: str) -> dict[str, Any]:
    return json.loads(row[field])
