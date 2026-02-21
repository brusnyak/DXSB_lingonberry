import sqlite3
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("dxsb.invest_journal")

class InvestmentJournal:
    """Tracks mid-term investment theses and monitoring levels."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS investments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                score REAL,
                discovery_type TEXT,
                logic TEXT,
                entry_zone TEXT,
                invalidation_level TEXT,
                inv_level REAL,
                target_potential TEXT,
                target_level REAL,
                status TEXT DEFAULT 'ACTIVE', -- 'ACTIVE', 'INVALIDATED', 'TARGET_REACHED'
                last_price REAL,
                report_path TEXT
            )
        """)
        conn.commit()
        conn.close()

    def add_thesis(self, symbol: str, score: float, d_type: str, logic: str, entry: str, invalidate: str, inv_level: float, target: str, target_level: float, report: str):
        ts_utc = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO investments (ts_utc, symbol, score, discovery_type, logic, entry_zone, invalidation_level, inv_level, target_potential, target_level, report_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts_utc, symbol, score, d_type, logic, entry, invalidate, inv_level, target, target_level, report))
        conn.commit()
        conn.close()
        logger.info(f"💾 Thesis Saved: {symbol} (Score: {score:.1f})")

    def get_active_investments(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM investments WHERE status = 'ACTIVE'").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_status(self, inv_id: int, status: str, last_price: float):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE investments SET status = ?, last_price = ? WHERE id = ?", (status, last_price, inv_id))
        conn.commit()
        conn.close()
        logger.info(f"📌 Status Updated: ID {inv_id} -> {status} (@ {last_price})")
