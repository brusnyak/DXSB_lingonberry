import os
import sys
import json

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.performance_journal import PerformanceJournal

def main():
    with open("config.json", "r") as f:
        config = json.load(f)
        
    journal = PerformanceJournal(config["database_path"])
    stats = journal.get_stats()
    
    print("\n" + "="*40)
    print("📈 PERFORMANCE SUMMARY")
    print("="*40)
    print(f"Total Trades: {stats['wins'] + stats['losses']}")
    print(f"Wins:         {stats['wins']}")
    print(f"Losses:       {stats['losses']}")
    print(f"Win Rate:     {stats['win_rate']:.1f}%")
    print(f"Total PnL:    {stats['total_pnl_pct']:.2f}%")
    print("="*40)

if __name__ == "__main__":
    main()
