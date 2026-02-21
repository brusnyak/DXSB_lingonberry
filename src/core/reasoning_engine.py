import logging
from typing import List, Dict, Optional
from src.analysis.ict_analyst import ICTPattern

logger = logging.getLogger("dxsb.reasoning")

class ReasoningEngine:
    """Converts technical patterns into human-readable signal reports and managed reminders."""
    
    def __init__(self, config: Dict):
        self.config = config

    def generate_initial_report(self, patterns: List[ICTPattern], quality: str) -> str:
        if not patterns:
            return "Stable market conditions. Trend following setup."
            
        confluence = [p for p in patterns if p.type == "Confluence"]
        pd_zones = [p for p in patterns if p.type == "PD_Zone"]
        main_patterns = [p for p in patterns if p.type in {"OB", "FVG"}]
        
        report_parts = []
        if confluence:
            c = confluence[0]
            report_parts.append(f"HIGH CONFLUENCE ({c.strength:.1f}): {c.context}")
        
        if pd_zones:
            p = pd_zones[0]
            report_parts.append(f"Price in {p.context}")

        if not confluence and main_patterns:
            p = main_patterns[0]
            report_parts.append(f"ICT SETUP: {p.direction} {p.type} detected ({p.context}).")
            
        return " | ".join(report_parts)

    def generate_reminder(self, reminder_count: int, signal_data: Dict) -> str:
        """Generates short reminders (max 2)."""
        symbol = signal_data.get("symbol", "?")
        if reminder_count == 1:
            return f"REMINDER 1: {symbol} setup still active. No execution detected."
        elif reminder_count == 2:
            return f"FINAL REMINDER: {symbol} entry window closing. Standing by."
        return ""

    def evaluate_pa_change(self, old_reasoning: str, new_patterns: List[ICTPattern]) -> Optional[str]:
        """Detects if PA has shifted to notify user."""
        if not new_patterns:
            return None
            
        new_report = self.generate_initial_report(new_patterns, "A") # Dummy quality
        if new_report != old_reasoning:
            # Check for specific structural changes
            for p in new_patterns:
                if p.type in {"BoS", "CHoCH"}:
                    return f"STRUCTURAL SHIFT: {p.direction} {p.type} detected. Context: {p.context}"
            return f"PA UPDATE: {new_report}"
        return None
