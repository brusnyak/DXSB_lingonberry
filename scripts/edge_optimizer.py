import sqlite3
import json
import os
import logging
import argparse
from typing import Dict, List

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("edge_optimizer")

def run_edge_audit(db_path: str = "dex_analytics.db", calibrate: bool = False):
    """
    Audits the outcomes of historical investment theses against recorded market snapshots.
    """
    if not os.path.exists(db_path):
        logger.error(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Query finished investments
    query = """
    SELECT * FROM investments 
    WHERE status IN ('TARGET_REACHED', 'INVALIDATED')
    """
    rows = conn.execute(query).fetchall()
    conn.close()

    if not rows:
        logger.info("No finished investments found for audit. Run more scans and monitor outcomes first.")
        return

    logger.info(f"📊 Auditing {len(rows)} historical outcomes...")

    regime_stats = {}
    
    for row in rows:
        metadata = json.loads(row["extra_metadata"]) if row["extra_metadata"] else {}
        regime = metadata.get("market_regime", "UNKNOWN")
        outcome = row["status"]
        
        if regime not in regime_stats:
            regime_stats[regime] = {"wins": 0, "total": 0, "rs_avg": 0.0}
        
        regime_stats[regime]["total"] += 1
        if outcome == "TARGET_REACHED":
            regime_stats[regime]["wins"] += 1
        
        regime_stats[regime]["rs_avg"] += metadata.get("rs_alpha", 0.0)

    # Calculate Win Rates and Correlations
    print("\n" + "="*50)
    print("EDGE OPTIMIZATION REPORT")
    print("="*50)
    
    calibration_data = {"regime_bonuses": {}}

    for regime, stats in regime_stats.items():
        win_rate = (stats["wins"] / stats["total"]) * 100
        avg_rs = stats["rs_avg"] / stats["total"]
        print(f"🌍 Regime: {regime}")
        print(f"   - Sample Size: {stats['total']}")
        print(f"   - Win Rate: {win_rate:.1f}%")
        print(f"   - Avg RS Alpha: {avg_rs:.4f}")
        
        # Calibration Logic
        if stats["total"] >= 3:
            if win_rate < 35:
                calibration_data["regime_bonuses"][regime] = -15.0
                print("   🔴 Suggestion: Apply Penalty (-15)")
            elif win_rate > 65:
                calibration_data["regime_bonuses"][regime] = 10.0
                print("   🟢 Suggestion: Apply Bonus (+10)")
        
        print("-" * 30)

    if calibrate:
        os.makedirs("config", exist_ok=True)
        with open("config/calibration.json", "w") as f:
            json.dump(calibration_data, f, indent=4)
        logger.info("✅ Calibration weights saved to config/calibration.json")
    
    print("="*50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true", help="Generate calibration weights")
    parser.add_argument("--db", default="dex_analytics.db", help="Path to database")
    args = parser.parse_args()
    
    run_edge_audit(db_path=args.db, calibrate=args.calibrate)
