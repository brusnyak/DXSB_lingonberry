import sqlite3
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("dxsb.journal")

class PerformanceJournal:
    """Tracks signal outcomes, win rates, and account growth."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                chain_id TEXT,
                adapter_type TEXT,
                entry_price REAL,
                exit_price REAL,
                pnl_pct REAL,
                pnl_usd REAL,
                outcome TEXT, -- 'TP', 'SL', 'EXPIRED', 'MANUAL'
                reasoning TEXT
            )
        """)
        conn.commit()
        conn.close()

    def log_trade(self, symbol: str, chain_id: str, adapter: str, entry: float, exit: float, pnl_pct: float, outcome: str, reasoning: str = ""):
        ts_utc = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO journal (ts_utc, symbol, chain_id, adapter_type, entry_price, exit_price, pnl_pct, outcome, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts_utc, symbol, chain_id, adapter, entry, exit, pnl_pct, outcome, reasoning))
        conn.commit()
        conn.close()
        logger.info(f"Journaled: {symbol} | Outcome: {outcome} | PnL: {pnl_pct:.2f}%")

    def get_stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        total = conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
        if total == 0:
            return {"total_trades": 0, "win_rate": 0, "total_growth": 0}
            
        wins = conn.execute("SELECT COUNT(*) FROM journal WHERE outcome = 'TP'").fetchone()[0]
        growth = conn.execute("SELECT SUM(pnl_pct) FROM journal").fetchone()[0] or 0.0
        
        conn.close()
        return {
            "total_trades": total,
            "win_rate": (wins / total) * 100,
            "total_pnl_pct": growth,
            "wins": wins,
            "losses": total - wins
        }
