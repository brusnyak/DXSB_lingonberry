import json
import os
import sqlite3
from typing import Dict, Iterable, List, Optional


class PlannerRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                symbol TEXT PRIMARY KEY,
                base_asset TEXT NOT NULL,
                quote_asset TEXT NOT NULL,
                tags TEXT,
                is_major INTEGER DEFAULT 0,
                is_seed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                updated_ts TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                event_ts TEXT NOT NULL,
                headline TEXT NOT NULL,
                url TEXT,
                strength REAL DEFAULT 1.0,
                UNIQUE(symbol, event_type, source, event_ts, headline)
            );

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                snapshot_ts TEXT PRIMARY KEY,
                total_equity REAL NOT NULL,
                total_equity_eur REAL DEFAULT 0.0,
                earn_equity REAL NOT NULL,
                spot_equity REAL NOT NULL,
                free_cash REAL NOT NULL,
                free_cash_eur REAL DEFAULT 0.0,
                locked_cash REAL NOT NULL,
                buying_power REAL NOT NULL,
                realized_pnl_usd REAL DEFAULT 0.0,
                unrealized_pnl_usd REAL DEFAULT 0.0,
                accrued_yield_usd REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS cash_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                amount REAL NOT NULL,
                value_usd REAL NOT NULL,
                value_eur REAL NOT NULL,
                bucket_type TEXT NOT NULL,
                source_snapshot_ts TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS earn_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                product_type TEXT NOT NULL,
                apr REAL DEFAULT 0.0,
                amount REAL NOT NULL,
                value_usd REAL NOT NULL,
                locked_until TEXT,
                status TEXT NOT NULL,
                source_snapshot_ts TEXT NOT NULL,
                accrued_yield_usd REAL DEFAULT 0.0,
                auto_subscribe INTEGER DEFAULT 0,
                redeemable INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS spot_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entry_ts TEXT NOT NULL,
                entry_price REAL NOT NULL,
                qty REAL NOT NULL,
                cost_usd REAL NOT NULL,
                stop_price REAL,
                tp1_price REAL,
                tp2_price REAL,
                status TEXT NOT NULL,
                max_hold_until TEXT,
                catalyst_event_id INTEGER,
                last_price REAL,
                unrealized_pnl_usd REAL DEFAULT 0.0,
                realized_pnl_usd REAL DEFAULT 0.0,
                close_ts TEXT,
                close_price REAL,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                sleeve TEXT NOT NULL,
                symbol_or_asset TEXT NOT NULL,
                action TEXT NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                capital_required_usd REAL DEFAULT 0.0,
                expires_ts TEXT,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ts TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                params_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS earn_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_ts TEXT NOT NULL,
                asset TEXT NOT NULL,
                product_type TEXT NOT NULL,
                apr REAL DEFAULT 0.0,
                duration_days INTEGER,
                min_purchase_amount REAL DEFAULT 0.0,
                can_purchase INTEGER DEFAULT 0,
                can_redeem INTEGER DEFAULT 0,
                is_sold_out INTEGER DEFAULT 0,
                is_hot INTEGER DEFAULT 0,
                status TEXT,
                extra_reward_asset TEXT,
                extra_reward_apr REAL DEFAULT 0.0,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS external_context_cache (
                provider TEXT NOT NULL,
                asset TEXT NOT NULL,
                fetched_ts TEXT NOT NULL,
                expires_ts TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (provider, asset)
            );

            CREATE TABLE IF NOT EXISTS research_candidate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol_or_asset TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                capital_required_usd REAL DEFAULT 0.0,
                reason TEXT NOT NULL,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS research_alert_state (
                symbol_or_asset TEXT NOT NULL,
                action TEXT NOT NULL,
                last_sent_ts TEXT NOT NULL,
                last_status TEXT NOT NULL,
                last_priority INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY (symbol_or_asset, action)
            );

            CREATE TABLE IF NOT EXISTS research_outcome_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol_or_asset TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_price REAL,
                ret_24h_pct REAL,
                ret_7d_pct REAL,
                quote_volume_usd_24h REAL,
                metadata_json TEXT
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(portfolio_snapshots)").fetchall()}
        if "total_equity_eur" not in columns:
            conn.execute("ALTER TABLE portfolio_snapshots ADD COLUMN total_equity_eur REAL DEFAULT 0.0")
        if "free_cash_eur" not in columns:
            conn.execute("ALTER TABLE portfolio_snapshots ADD COLUMN free_cash_eur REAL DEFAULT 0.0")
        conn.commit()
        conn.close()

    def upsert_assets(self, assets: Iterable[Dict]) -> None:
        conn = self._connect()
        conn.executemany(
            """
            INSERT INTO assets (symbol, base_asset, quote_asset, tags, is_major, is_seed, status, updated_ts)
            VALUES (:symbol, :base_asset, :quote_asset, :tags, :is_major, :is_seed, :status, :updated_ts)
            ON CONFLICT(symbol) DO UPDATE SET
                base_asset=excluded.base_asset,
                quote_asset=excluded.quote_asset,
                tags=excluded.tags,
                is_major=excluded.is_major,
                is_seed=excluded.is_seed,
                status=excluded.status,
                updated_ts=excluded.updated_ts
            """,
            list(assets),
        )
        conn.commit()
        conn.close()

    def insert_events(self, events: Iterable[Dict]) -> int:
        rows = list(events)
        conn = self._connect()
        before = conn.total_changes
        conn.executemany(
            """
            INSERT OR IGNORE INTO events (symbol, event_type, source, event_ts, headline, url, strength)
            VALUES (:symbol, :event_type, :source, :event_ts, :headline, :url, :strength)
            """,
            rows,
        )
        conn.commit()
        inserted = conn.total_changes - before
        conn.close()
        return inserted

    def recent_events(self, max_age_days: int) -> List[Dict]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT *
            FROM events
            WHERE julianday('now') - julianday(replace(replace(event_ts, 'Z', ''), 'T', ' ')) <= ?
            ORDER BY event_ts DESC, strength DESC
            """,
            (max_age_days,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def record_snapshot(self, snapshot: Dict, earn_positions: Iterable[Dict], spot_positions: Iterable[Dict], cash_balances: Iterable[Dict]) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO portfolio_snapshots (
                snapshot_ts, total_equity, total_equity_eur, earn_equity, spot_equity, free_cash, free_cash_eur, locked_cash,
                buying_power, realized_pnl_usd, unrealized_pnl_usd, accrued_yield_usd
            ) VALUES (
                :snapshot_ts, :total_equity, :total_equity_eur, :earn_equity, :spot_equity, :free_cash, :free_cash_eur, :locked_cash,
                :buying_power, :realized_pnl_usd, :unrealized_pnl_usd, :accrued_yield_usd
            )
            """,
            snapshot,
        )
        conn.execute("DELETE FROM earn_positions WHERE source_snapshot_ts = ?", (snapshot["snapshot_ts"],))
        conn.execute("DELETE FROM cash_balances WHERE source_snapshot_ts = ?", (snapshot["snapshot_ts"],))
        conn.execute("DELETE FROM spot_positions WHERE status IN ('SYNCED', 'UNRECONCILED') AND close_ts IS NULL")
        conn.executemany(
            """
            INSERT INTO cash_balances (
                asset, amount, value_usd, value_eur, bucket_type, source_snapshot_ts
            ) VALUES (
                :asset, :amount, :value_usd, :value_eur, :bucket_type, :source_snapshot_ts
            )
            """,
            list(cash_balances),
        )
        conn.executemany(
            """
            INSERT INTO earn_positions (
                asset, product_type, apr, amount, value_usd, locked_until, status,
                source_snapshot_ts, accrued_yield_usd, auto_subscribe, redeemable
            ) VALUES (
                :asset, :product_type, :apr, :amount, :value_usd, :locked_until, :status,
                :source_snapshot_ts, :accrued_yield_usd, :auto_subscribe, :redeemable
            )
            """,
            list(earn_positions),
        )
        conn.executemany(
            """
            INSERT INTO spot_positions (
                symbol, entry_ts, entry_price, qty, cost_usd, stop_price, tp1_price, tp2_price,
                status, max_hold_until, catalyst_event_id, last_price, unrealized_pnl_usd,
                realized_pnl_usd, close_ts, close_price, notes
            ) VALUES (
                :symbol, :entry_ts, :entry_price, :qty, :cost_usd, :stop_price, :tp1_price, :tp2_price,
                :status, :max_hold_until, :catalyst_event_id, :last_price, :unrealized_pnl_usd,
                :realized_pnl_usd, :close_ts, :close_price, :notes
            )
            """,
            list(spot_positions),
        )
        conn.commit()
        conn.close()

    def latest_snapshot(self) -> Optional[Dict]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY snapshot_ts DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def latest_earn_positions(self) -> List[Dict]:
        snapshot = self.latest_snapshot()
        if not snapshot:
            return []
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM earn_positions WHERE source_snapshot_ts = ? ORDER BY value_usd DESC",
            (snapshot["snapshot_ts"],),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def latest_cash_balances(self) -> List[Dict]:
        snapshot = self.latest_snapshot()
        if not snapshot:
            return []
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM cash_balances WHERE source_snapshot_ts = ? ORDER BY value_usd DESC",
            (snapshot["snapshot_ts"],),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def open_spot_positions(self) -> List[Dict]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT *
            FROM spot_positions
            WHERE status IN ('OPEN', 'SYNCED', 'UNRECONCILED')
              AND close_ts IS NULL
            ORDER BY entry_ts DESC
            """
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def closed_spot_positions(self) -> List[Dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM spot_positions WHERE close_ts IS NOT NULL ORDER BY close_ts DESC"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_recommendations(self, rows: Iterable[Dict]) -> None:
        conn = self._connect()
        conn.executemany(
            """
            INSERT INTO recommendations (
                ts, sleeve, symbol_or_asset, action, priority, status, reason,
                capital_required_usd, expires_ts, metadata_json
            ) VALUES (
                :ts, :sleeve, :symbol_or_asset, :action, :priority, :status, :reason,
                :capital_required_usd, :expires_ts, :metadata_json
            )
            """,
            list(rows),
        )
        conn.commit()
        conn.close()

    def record_research_candidates(self, rows: Iterable[Dict]) -> None:
        payload = [row for row in rows if row.get("sleeve") == "research"]
        if not payload:
            return
        conn = self._connect()
        conn.executemany(
            """
            INSERT INTO research_candidate_history (
                ts, symbol_or_asset, action, status, priority,
                capital_required_usd, reason, metadata_json
            ) VALUES (
                :ts, :symbol_or_asset, :action, :status, :priority,
                :capital_required_usd, :reason, :metadata_json
            )
            """,
            payload,
        )
        conn.commit()
        conn.close()

    def research_candidate_stats(self) -> Dict[str, Dict]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT
                symbol_or_asset,
                COUNT(*) AS scans,
                SUM(CASE WHEN status = 'actionable' THEN 1 ELSE 0 END) AS actionable_count,
                SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked_count,
                SUM(CASE WHEN status = 'watchlist' THEN 1 ELSE 0 END) AS watchlist_count,
                MIN(ts) AS first_ts,
                MAX(ts) AS last_ts
            FROM research_candidate_history
            GROUP BY symbol_or_asset
            """
        ).fetchall()
        conn.close()
        return {
            row["symbol_or_asset"]: dict(row)
            for row in rows
        }

    def recent_recommendations(self, limit: int = 20) -> List[Dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM recommendations ORDER BY ts DESC, priority DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def research_alert_state_map(self) -> Dict[str, Dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM research_alert_state"
        ).fetchall()
        conn.close()
        return {
            f"{row['symbol_or_asset']}::{row['action']}": dict(row)
            for row in rows
        }

    def upsert_research_alert_state(self, rows: Iterable[Dict]) -> None:
        payload = list(rows)
        if not payload:
            return
        conn = self._connect()
        conn.executemany(
            """
            INSERT INTO research_alert_state (
                symbol_or_asset, action, last_sent_ts, last_status, last_priority, fingerprint
            ) VALUES (
                :symbol_or_asset, :action, :last_sent_ts, :last_status, :last_priority, :fingerprint
            )
            ON CONFLICT(symbol_or_asset, action) DO UPDATE SET
                last_sent_ts=excluded.last_sent_ts,
                last_status=excluded.last_status,
                last_priority=excluded.last_priority,
                fingerprint=excluded.fingerprint
            """,
            payload,
        )
        conn.commit()
        conn.close()

    def record_research_outcome_snapshots(self, rows: Iterable[Dict]) -> None:
        payload = list(rows)
        if not payload:
            return
        conn = self._connect()
        conn.executemany(
            """
            INSERT INTO research_outcome_snapshots (
                ts, symbol_or_asset, action, status, entry_price,
                ret_24h_pct, ret_7d_pct, quote_volume_usd_24h, metadata_json
            ) VALUES (
                :ts, :symbol_or_asset, :action, :status, :entry_price,
                :ret_24h_pct, :ret_7d_pct, :quote_volume_usd_24h, :metadata_json
            )
            """,
            payload,
        )
        conn.commit()
        conn.close()

    def recent_research_outcomes(self, symbol_or_asset: str, limit: int = 10) -> List[Dict]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT *
            FROM research_outcome_snapshots
            WHERE symbol_or_asset = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (symbol_or_asset, limit),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def save_backtest_run(self, run_ts: str, strategy_name: str, params: Dict, metrics: Dict) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO backtest_runs (run_ts, strategy_name, params_json, metrics_json)
            VALUES (?, ?, ?, ?)
            """,
            (run_ts, strategy_name, json.dumps(params), json.dumps(metrics)),
        )
        conn.commit()
        conn.close()

    def latest_backtest_run(self) -> Optional[Dict]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM backtest_runs ORDER BY run_ts DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def replace_earn_products(self, snapshot_ts: str, rows: Iterable[Dict]) -> None:
        payload = list(rows)
        conn = self._connect()
        conn.execute("DELETE FROM earn_products WHERE snapshot_ts = ?", (snapshot_ts,))
        conn.executemany(
            """
            INSERT INTO earn_products (
                snapshot_ts, asset, product_type, apr, duration_days, min_purchase_amount,
                can_purchase, can_redeem, is_sold_out, is_hot, status, extra_reward_asset,
                extra_reward_apr, raw_json
            ) VALUES (
                :snapshot_ts, :asset, :product_type, :apr, :duration_days, :min_purchase_amount,
                :can_purchase, :can_redeem, :is_sold_out, :is_hot, :status, :extra_reward_asset,
                :extra_reward_apr, :raw_json
            )
            """,
            payload,
        )
        conn.commit()
        conn.close()

    def latest_earn_products(self) -> List[Dict]:
        conn = self._connect()
        row = conn.execute(
            "SELECT snapshot_ts FROM earn_products ORDER BY snapshot_ts DESC LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            return []
        rows = conn.execute(
            """
            SELECT *
            FROM earn_products
            WHERE snapshot_ts = ?
            ORDER BY apr DESC, is_hot DESC, can_purchase DESC, asset ASC
            """,
            (row["snapshot_ts"],),
        ).fetchall()
        conn.close()
        return [dict(item) for item in rows]

    def get_cached_context(self, provider: str, asset: str, now_ts: str) -> Optional[Dict]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT *
            FROM external_context_cache
            WHERE provider = ?
              AND asset = ?
              AND expires_ts >= ?
            """,
            (provider, asset, now_ts),
        ).fetchone()
        conn.close()
        if not row:
            return None
        payload = dict(row)
        payload["payload"] = json.loads(payload["payload_json"])
        return payload

    def upsert_cached_context(self, provider: str, asset: str, fetched_ts: str, expires_ts: str, payload: Dict) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO external_context_cache (provider, asset, fetched_ts, expires_ts, payload_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, asset) DO UPDATE SET
                fetched_ts=excluded.fetched_ts,
                expires_ts=excluded.expires_ts,
                payload_json=excluded.payload_json
            """,
            (provider, asset, fetched_ts, expires_ts, json.dumps(payload)),
        )
        conn.commit()
        conn.close()

    def reconcile_spot_position(self, payload: Dict) -> None:
        conn = self._connect()
        if payload.get("id"):
            conn.execute(
                """
                UPDATE spot_positions
                SET entry_ts=:entry_ts,
                    entry_price=:entry_price,
                    qty=:qty,
                    cost_usd=:cost_usd,
                    stop_price=:stop_price,
                    tp1_price=:tp1_price,
                    tp2_price=:tp2_price,
                    status=:status,
                    max_hold_until=:max_hold_until,
                    last_price=:last_price,
                    unrealized_pnl_usd=:unrealized_pnl_usd,
                    realized_pnl_usd=:realized_pnl_usd,
                    close_ts=:close_ts,
                    close_price=:close_price,
                    notes=:notes
                WHERE id=:id
                """,
                payload,
            )
        else:
            conn.execute(
                """
                INSERT INTO spot_positions (
                    symbol, entry_ts, entry_price, qty, cost_usd, stop_price, tp1_price, tp2_price,
                    status, max_hold_until, catalyst_event_id, last_price, unrealized_pnl_usd,
                    realized_pnl_usd, close_ts, close_price, notes
                ) VALUES (
                    :symbol, :entry_ts, :entry_price, :qty, :cost_usd, :stop_price, :tp1_price, :tp2_price,
                    :status, :max_hold_until, :catalyst_event_id, :last_price, :unrealized_pnl_usd,
                    :realized_pnl_usd, :close_ts, :close_price, :notes
                )
                """,
                payload,
            )
        conn.commit()
        conn.close()
