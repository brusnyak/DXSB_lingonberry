import logging
import time
import math
import os
import json
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("dxsb.ict")

@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class ICTPattern:
    type: str  # "OB", "FVG", "BOS", "CHoCH", "Liquidity", "Trend", "Sweep", "Investment"
    direction: str  # "BULLISH", "BEARISH", "NEUTRAL"
    price_range: tuple  # (low, high)
    strength: float
    context: str
    timestamp: int
    symbol: Optional[str] = None

@dataclass
class InvestmentResult:
    symbol: str
    score: float  # 0-100
    discovery_type: str  # "Expansion", "Accumulation", "Momentum"
    logic: str
    target_potential: str
    target_level: float
    entry_zone: str  # OTE zone
    invalidation_level: str
    inv_level: float
    timestamp: int
    url: Optional[str] = None
    extra_metadata: Optional[Dict] = None # For learning/journaling

class ICTAnalyst:
    """Detects ICT patterns (BOS, CHoCH, Sweeps) with EMA trend filtering."""
    
    def __init__(self, sensitivity: float = 1.0):
        self.sensitivity = sensitivity
        self.calibration = self._load_calibration()

    def _load_calibration(self) -> Dict:
        path = "config/calibration.json"
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load calibration: {e}")
        return {}

    def analyze(self, candles: List[Candle]) -> List[ICTPattern]:
        if len(candles) < 50:
            return []
            
        patterns = []
        
        # 1. Trend Filter (EMA 50/200)
        ema50 = self._calculate_ema(candles, 50)
        ema200 = self._calculate_ema(candles, 200)
        current_trend = "NEUTRAL"
        if ema50 and ema200:
            if ema50[-1] > ema200[-1]:
                current_trend = "BULLISH"
            else:
                current_trend = "BEARISH"
            
            patterns.append(ICTPattern(
                type="Trend",
                direction=current_trend,
                price_range=(ema200[-1], ema50[-1]),
                strength=1.0,
                context=f"Overall Trend: {current_trend} (EMA 50/200)",
                timestamp=candles[-1].timestamp
            ))

        # 2. Market Structure (Swing Points, BOS, CHoCH)
        structure_patterns = self._find_structure(candles)
        patterns.extend(structure_patterns)
        
        # 3. Sweeps & Liquidity
        pivots = self._find_pivots(candles)
        patterns.extend(self._find_liquidity(candles, pivots))
        patterns.extend(self._find_sweeps(candles, pivots))
        
        # 4. Classical POIs (FVG, OB)
        fvgs = self._find_fvgs(candles)
        obs = self._find_order_blocks(candles)
        patterns.extend(fvgs)
        patterns.extend(obs)
        
        # 5. PD Zones
        pd_zone = self._get_pd_zone(candles)
        if pd_zone:
            patterns.append(pd_zone)

        # 6. Final Confluence
        confluence = self._calculate_confluence(candles, patterns, current_trend)
        if confluence:
            patterns.append(confluence)
        
        return patterns

    def _classify_regime(self, candles: List[Candle]) -> str:
        """Classifies market state: QUIET, MOMENTUM, VOLATILE, BEARISH."""
        if len(candles) < 50: return "QUIET"
        
        # 1. Bearish Filter (EMA 200)
        ema200 = self._calculate_ema(candles, 200)
        current = candles[-1].close
        if ema200 and current < ema200[-1]:
            return "BEARISH"
            
        # 2. Volatility Check (ATR Ratio)
        atr_10 = sum(c.high - c.low for c in candles[-10:]) / 10
        atr_30 = sum(c.high - c.low for c in candles[-30:]) / 30
        vpc_ratio = atr_10 / atr_30 if atr_30 > 0 else 1.0
        
        # 3. Trend Intensity (EMA 50 Slope)
        ema50 = self._calculate_ema(candles, 50)
        if len(ema50) >= 10:
            slope = (ema50[-1] - ema50[-10]) / ema50[-10]
        else:
            slope = 0.0
            
        if vpc_ratio > 1.3:
            return "VOLATILE"
        if slope > 0.005: 
            return "MOMENTUM"
        if vpc_ratio < 0.85:
            return "QUIET"
            
        return "NORMAL"

    def _calculate_ema(self, candles: List[Candle], period: int) -> List[float]:
        if len(candles) < period:
            return []
        closes = [c.close for c in candles]
        ema = []
        k = 2 / (period + 1)
        sma = sum(closes[:period]) / period
        ema.append(sma)
        for i in range(period, len(closes)):
            val = (closes[i] * k) + (ema[-1] * (1 - k))
            ema.append(val)
        return ema

    def _find_pivots(self, candles: List[Candle], left_bars: int = 3, right_bars: int = 3) -> List[Dict]:
        pivots = []
        for i in range(left_bars, len(candles) - right_bars):
            is_high = all(candles[j].high <= candles[i].high for j in range(i-left_bars, i+right_bars+1))
            if is_high:
                pivots.append({"type": "HH", "price": candles[i].high, "index": i, "timestamp": candles[i].timestamp})
            
            is_low = all(candles[j].low >= candles[i].low for j in range(i-left_bars, i+right_bars+1))
            if is_low:
                pivots.append({"type": "LL", "price": candles[i].low, "index": i, "timestamp": candles[i].timestamp})
        return pivots

    def _find_structure(self, candles: List[Candle]) -> List[ICTPattern]:
        pivots = self._find_pivots(candles, 4, 3)
        if len(pivots) < 4: return []
        
        patterns = []
        last_high = pivots[0] if pivots[0]["type"] == "HH" else pivots[1]
        last_low = pivots[0] if pivots[0]["type"] == "LL" else pivots[1]
        
        market_direction = "NEUTRAL"
        
        # Displacement calculation
        avg_body = sum(abs(c.close - c.open) for c in candles[-10:]) / 10
        
        for i in range(2, len(pivots)):
            cur = pivots[i]
            # Find the candle that broke the pivot level
            breaking_candle = candles[cur["index"]]
            body_size = abs(breaking_candle.close - breaking_candle.open)
            is_displaced = body_size > (avg_body * 1.5)
            
            if cur["type"] == "HH":
                if cur["price"] > last_high["price"]:
                    patterns.append(ICTPattern(
                        type="BOS", direction="BULLISH",
                        price_range=(last_high["price"], cur["price"]),
                        strength=3.0 if is_displaced else 1.0, 
                        context="Bullish BOS" + (" (Displaced)" if is_displaced else ""),
                        timestamp=cur["timestamp"]
                    ))
                    market_direction = "BULLISH"
                elif market_direction == "BEARISH" and cur["price"] > last_high["price"]:
                    patterns.append(ICTPattern(
                        type="CHoCH", direction="BULLISH",
                        price_range=(last_high["price"], cur["price"]),
                        strength=4.0 if is_displaced else 2.0, 
                        context="Bullish CHoCH" + (" (Displaced)" if is_displaced else ""),
                        timestamp=cur["timestamp"]
                    ))
                    market_direction = "BULLISH"
                last_high = cur
            else: # LL
                if cur["price"] < last_low["price"]:
                    patterns.append(ICTPattern(
                        type="BOS", direction="BEARISH",
                        price_range=(cur["price"], last_low["price"]),
                        strength=3.0 if is_displaced else 1.0, 
                        context="Bearish BOS" + (" (Displaced)" if is_displaced else ""),
                        timestamp=cur["timestamp"]
                    ))
                    market_direction = "BEARISH"
                elif market_direction == "BULLISH" and cur["price"] < last_low["price"]:
                    patterns.append(ICTPattern(
                        type="CHoCH", direction="BEARISH",
                        price_range=(cur["price"], last_low["price"]),
                        strength=4.0 if is_displaced else 2.0, 
                        context="Bearish CHoCH" + (" (Displaced)" if is_displaced else ""),
                        timestamp=cur["timestamp"]
                    ))
                    market_direction = "BEARISH"
                last_low = cur
        return patterns

    def _find_sweeps(self, candles: List[Candle], pivots: List[Dict]) -> List[ICTPattern]:
        if len(pivots) < 2: return []
        patterns = []
        
        # Check all candles for potential sweeps of recent pivots
        for i in range(len(candles)):
            c = candles[i]
            # Check recent pivots (within last 50 bars)
            recent_pivots = [p for p in pivots if i - 50 < p["index"] < i]
            for p in recent_pivots:
                if p["type"] == "LL" and c.low < p["price"] and c.close > p["price"]:
                    patterns.append(ICTPattern(
                        type="Sweep", direction="BULLISH",
                        price_range=(c.low, p["price"]),
                        strength=4.0, context=f"Sweep of Low {p['price']:.8f}",
                        timestamp=c.timestamp
                    ))
                elif p["type"] == "HH" and c.high > p["price"] and c.close < p["price"]:
                    patterns.append(ICTPattern(
                        type="Sweep", direction="BEARISH",
                        price_range=(p["price"], c.high),
                        strength=4.0, context=f"Sweep of High {p['price']:.8f}",
                        timestamp=c.timestamp
                    ))
        return patterns

    def _find_fvgs(self, candles: List[Candle]) -> List[ICTPattern]:
        fvgs = []
        for i in range(2, len(candles)):
            if candles[i-2].high < candles[i].low:
                patterns_after = candles[i+1:]
                mitigated = any(c.low <= candles[i-2].high for c in patterns_after)
                if not mitigated:
                    fvgs.append(ICTPattern(
                        type="FVG", direction="BULLISH",
                        price_range=(candles[i-2].high, candles[i].low),
                        strength=2.0, context="Unmitigated Bullish FVG",
                        timestamp=candles[i-1].timestamp
                    ))
            elif candles[i-2].low > candles[i].high:
                patterns_after = candles[i+1:]
                mitigated = any(c.high >= candles[i-2].low for c in patterns_after)
                if not mitigated:
                    fvgs.append(ICTPattern(
                        type="FVG", direction="BEARISH",
                        price_range=(candles[i].high, candles[i-2].low),
                        strength=2.0, context="Unmitigated Bearish FVG",
                        timestamp=candles[i-1].timestamp
                    ))
        return fvgs

    def _find_order_blocks(self, candles: List[Candle]) -> List[ICTPattern]:
        """Detects Order Blocks (OB) - the last candle before a significant displacement."""
        obs = []
        # We look for a "Body Displacement" > 2x average body over last 20
        avg_body = sum(abs(c.close - c.open) for c in candles[-20:]) / 20
        
        for i in range(1, len(candles) - 1):
            # Bullish OB (Down candle before Up move)
            if candles[i].close < candles[i].open:
                expansion = candles[i+1].close - candles[i+1].open
                if expansion > avg_body * 2.0:
                    # check for mitigation within 30 candles
                    future = candles[i+2 : i+32]
                    mitigated = any(c.low < candles[i].low for c in future)
                    if not mitigated:
                        obs.append(ICTPattern(
                            type="OB", direction="BULLISH",
                            price_range=(candles[i].low, candles[i].high),
                            strength=3.0, context="Structural Bullish OB (Demand)",
                            timestamp=candles[i].timestamp
                        ))
            # Bearish OB (Up candle before Down move)
            elif candles[i].close > candles[i].open:
                expansion = candles[i+1].open - candles[i+1].close
                if expansion > avg_body * 2.0:
                    future = candles[i+2 : i+32]
                    mitigated = any(c.high > candles[i].high for c in future)
                    if not mitigated:
                        obs.append(ICTPattern(
                            type="OB", direction="BEARISH",
                            price_range=(candles[i].low, candles[i].high),
                            strength=3.0, context="Structural Bearish OB (Supply)",
                            timestamp=candles[i].timestamp
                        ))
        return obs

    def _get_pd_zone(self, candles: List[Candle], lookback: int = 50) -> Optional[ICTPattern]:
        if len(candles) < lookback: return None
        window = candles[-lookback:]
        high = max(c.high for c in window)
        low = min(c.low for c in window)
        eq = (high + low) / 2
        current = candles[-1].close
        return ICTPattern(
            type="PD_Zone", direction="BULLISH" if current < eq else "BEARISH",
            price_range=(low, high), strength=1.0,
            context=f"Price in {'Discount' if current < eq else 'Premium'} Zone",
            timestamp=candles[-1].timestamp
        )

    def _calculate_confluence(self, candles: List[Candle], patterns: List[ICTPattern], htf_trend: str) -> Optional[ICTPattern]:
        current = candles[-1].close
        score = 0.0
        details = []
        
        # Filter patterns that happened recently (last 25 bars for entry context)
        recent_ts = candles[-25].timestamp
        recent_patterns = [p for p in patterns if p.timestamp >= recent_ts]
        all_time_patterns = patterns 
        
        if htf_trend == "NEUTRAL": return None
        
        # 0. Momentum Check (Last 5 candles)
        # We don't want to buy if the last 5 candles were massive red ones (crashing)
        last_5 = candles[-5:]
        net_move = current - last_5[0].open
        momentum_dir = "BULLISH" if net_move > 0 else "BEARISH"
        avg_bar_size = sum(abs(c.high - c.low) for c in last_5) / 5
        is_volatile = abs(net_move) > avg_bar_size * 2
        
        # 1. Structural Breaks
        bull_choch = [p for p in recent_patterns if p.type == "CHoCH" and p.direction == "BULLISH"]
        bear_choch = [p for p in recent_patterns if p.type == "CHoCH" and p.direction == "BEARISH"]
        bull_bos = [p for p in recent_patterns if p.type == "BOS" and p.direction == "BULLISH"]
        bear_bos = [p for p in recent_patterns if p.type == "BOS" and p.direction == "BEARISH"]
        
        sig_direction = "NEUTRAL"
        # Only favor structural breaks that match the immediate momentum if volatile
        if htf_trend == "BULLISH":
            if bull_choch:
                if is_volatile and momentum_dir != "BULLISH": pass # Reject if crashing
                else: score += 4.0; sig_direction = "BULLISH"; details.append("Bullish CHoCH")
            elif bull_bos:
                score += 2.0; sig_direction = "BULLISH"; details.append("Bullish BOS")
        elif htf_trend == "BEARISH":
            if bear_choch:
                if is_volatile and momentum_dir != "BEARISH": pass
                else: score += 4.0; sig_direction = "BEARISH"; details.append("Bearish CHoCH")
            elif bear_bos:
                score += 2.0; sig_direction = "BEARISH"; details.append("Bearish BOS")
        
        # Counter-Trend Handling (High requirement)
        if sig_direction == "NEUTRAL":
            if htf_trend == "BULLISH" and bear_choch and bear_bos:
                score += 3.0; sig_direction = "BEARISH"; details.append("Counter-trend Reversal")
            elif htf_trend == "BEARISH" and bull_choch and bull_bos:
                score += 3.0; sig_direction = "BULLISH"; details.append("Counter-trend Reversal")
        
        if sig_direction == "NEUTRAL": return None
        
        # Displacement check for the signal itself
        sig_patterns = [p for p in recent_patterns if p.type in {"BOS", "CHoCH"} and p.direction == sig_direction]
        if any("(Displaced)" in p.context for p in sig_patterns):
            score += 2.0
            details.append("Displacement Found")

        # 2. Sweeps
        sweep = [p for p in recent_patterns if p.type == "Sweep" and p.direction == sig_direction]
        if sweep:
            score += 4.0 # Sweeps are vital for 60% WR
            details.append("Liquidity Sweep")
            
        # 3. Target Discovery
        target_type = "EQH" if sig_direction == "BULLISH" else "EQL"
        found_target = [p for p in all_time_patterns if p.type == "Liquidity" and target_type in p.context]
        valid_targets = []
        for t in found_target:
            t_price = (t.price_range[0] + t.price_range[1]) / 2
            if sig_direction == "BULLISH" and t_price > current:
                valid_targets.append((t_price, abs(t_price - current)))
            elif sig_direction == "BEARISH" and t_price < current:
                valid_targets.append((t_price, abs(t_price - current)))
        if valid_targets:
            valid_targets.sort(key=lambda x: x[1])
            target_price = valid_targets[0][0]
            score += 2.0; details.append(f"Targeting {target_type}: {target_price:.8f}"); details.append(f"TP_TARGET:{target_price}")
            
        # 4. POI Refinement
        for p in recent_patterns:
            if p.type in {"FVG", "OB"} and p.direction == sig_direction:
                if p.price_range[0] * 0.9997 <= current <= p.price_range[1] * 1.0003:
                    score += 2.0; details.append(f"Inside {p.type}")
                    break
        
        # 5. PD Zone Check
        pd = [p for p in all_time_patterns if p.type == "PD_Zone"]
        if pd:
            is_discount = current < (pd[-1].price_range[0] + pd[-1].price_range[1])/2
            if sig_direction == "BULLISH" and is_discount: score += 1.0; details.append("Discount Zone")
            elif sig_direction == "BEARISH" and not is_discount: score += 1.0; details.append("Premium Zone")

        # 6. Final Selection (Stricter for 60% WR)
        if score >= 6.5: 
            return ICTPattern(
                type="Confluence", direction=sig_direction,
                price_range=(current, current), strength=score,
                context="; ".join(details), timestamp=candles[-1].timestamp
            )
        return None

    def calculate_investment_score(self, candles: List[Candle], symbol: str, benchmark_candles: Optional[List[Candle]] = None, sector_candles: Optional[List[Candle]] = None, sentiment_bonus: float = 0.0, url: Optional[str] = None) -> InvestmentResult:
        """Ranks an asset for mid-term investment potential (The 'ENSO' Model)."""
        if len(candles) < 50:
            return InvestmentResult(
                symbol=symbol, score=0, discovery_type="None", 
                logic="Insufficient data", target_potential="N/A", 
                target_level=0.0, entry_zone="N/A", invalidation_level="N/A", 
                inv_level=0.0, timestamp=int(time.time()), url=url,
                extra_metadata={}
            )
        
        current = candles[-1].close
        score = 50.0 # Base score
        logic_details = []
        
        # Phase 16: External Sentiment Overlay
        if sentiment_bonus != 0:
            score += sentiment_bonus
            logic_details.append(f"Sentiment Bias: {sentiment_bonus:+.1f}")
        
        # Phase 14: Market Regime Detection
        regime = self._classify_regime(candles)
        logic_details.append(f"Regime: {regime}")
        
        # Phase 15: Adaptive Calibration
        regime_bonus = self.calibration.get("regime_bonuses", {}).get(regime, 0.0)
        score += regime_bonus
        if regime_bonus != 0:
            logic_details.append(f"Calibration Bias: {regime_bonus:+.1f}")
        
        # 1. Volatility Contraction (VPC)
        atr_10 = sum(c.high - c.low for c in candles[-10:]) / 10
        atr_30 = sum(c.high - c.low for c in candles[-30:]) / 30
        vpc_ratio = atr_10 / atr_30 if atr_30 > 0 else 1.0
        
        # Weights change based on regime
        w_vpc = 20 if regime == "QUIET" else 10
        w_rs = 25 if regime == "MOMENTUM" else 15
        w_struct = 15
        w_value = 25 if regime in ["QUIET", "BEARISH"] else 15

        if vpc_ratio < 0.8:
            score += w_vpc
            logic_details.append(f"VPC Tightening ({vpc_ratio:.2f})")
        elif vpc_ratio > 1.2:
            score += 10
            logic_details.append(f"VPC Expansion ({vpc_ratio:.2f})")

        # 2. Relative Strength (RS)
        rs_alpha = 0.0
        if benchmark_candles and len(benchmark_candles) >= 30:
            asset_ret = (candles[-1].close / candles[-30].close) - 1
            bench_ret = (benchmark_candles[-1].close / benchmark_candles[-30].close) - 1
            rs_alpha = asset_ret - bench_ret
            
            if rs_alpha > 0.05:
                score += w_rs
                logic_details.append(f"RS Outperforming (+{rs_alpha*100:.1f}%)")
            elif rs_alpha < -0.05:
                score -= 15
                logic_details.append(f"RS Underperforming ({rs_alpha*100:.1f}%)")

        # 2b. Sector Alpha (Phase 16)
        sector_alpha = 0.0
        if sector_candles and len(sector_candles) >= 30:
            asset_ret = (candles[-1].close / candles[-30].close) - 1
            sector_ret = (sector_candles[-1].close / sector_candles[-30].close) - 1
            sector_alpha = asset_ret - sector_ret
            
            if sector_alpha > 0.03: # Outperforming sector by 3%+
                score += 15
                logic_details.append(f"🚀 Sector Leader (+{sector_alpha*100:.1f}%)")
            elif sector_alpha < -0.03:
                score -= 10
                logic_details.append(f"🐢 Sector Laggard ({sector_alpha*100:.1f}%)")

        # 3. Structural Alignment (Macro)
        patterns = self.analyze(candles)
        bull_struct = [p for p in patterns if p.type in {"BOS", "CHoCH"} and p.direction == "BULLISH"]
        if bull_struct:
            score += w_struct
            logic_details.append(f"Bullish Structure ({len(bull_struct)} breaks)")
        
        # 4. Trend Alignment (Daily EMA)
        trend = [p for p in patterns if p.type == "Trend"]
        if trend and trend[-1].direction == "BULLISH":
            score += 10
            logic_details.append("Bullish Daily Trend")
        
        # 5. Volume Surge
        v_now = sum(c.volume for c in candles[-5:]) / 5
        v_prev = sum(c.volume for c in candles[-30:-5]) / 25
        vol_ratio = v_now / v_prev if v_prev > 0 else 1.0
        if vol_ratio > 1.5:
            score += 15
            logic_details.append(f"Volume Surge ({vol_ratio:.1f}x)")

        # 6. Value Discovery (Demand Zones & Sweeps)
        obs = [p for p in patterns if p.type == "OB" and p.direction == "BULLISH"]
        sweeps = [p for p in patterns if p.type == "Sweep" and p.direction == "BULLISH"]
        
        proximity_bonus = 0
        for ob in obs:
            ob_low, ob_high = ob.price_range
            if (current >= ob_low * 0.99) and (current <= ob_high * 1.05):
                proximity_bonus = max(proximity_bonus, w_value)
                logic_details.append("📌 Testing Structural Demand Zone")
                break
        score += proximity_bonus

        recent_ts = candles[-15].timestamp
        recent_sweep = any(s for s in sweeps if s.timestamp >= recent_ts)
        if recent_sweep:
            score += 15
            logic_details.append("🛡️ Sell-Side Liquidity Swept")

        # 7. PD Discount Logic
        pd = self._get_pd_zone(candles)
        if pd and "Discount" in pd.context:
            score += 10
            logic_details.append("🏷️ Institutional Discount Zone")
        
        # 8. Bearish Filter Penalty
        if regime == "BEARISH":
            score *= 0.7 # Significant penalty for being in a macro downtrend
            logic_details.append("⚠️ Macro Bearish Regime: High Invalidation Risk")

        discovery_type = "Accumulation" if vpc_ratio < 1.0 else "Expansion"

        # Cap score
        score = min(score, 100)
        score = max(score, 0)

        # 6. Entry Optimization (OTE - Optimal Trade Entry)
        # We look for a recent expansion leg to retrace into
        entry_zone = "Market Entry (Wait for Pullback)"
        invalidation = "Below Recent Structure"
        
        # Simple Fibonacci OTE logic (D1/H4)
        # Find highest high and lowest low in the last 50 candles
        h_50 = max(c.high for c in candles[-50:])
        l_50 = min(c.low for c in candles[-50:])
        f_range = h_50 - l_50
        
        if f_range > 0:
            ote_high = h_50 - (f_range * 0.62)
            ote_low = h_50 - (f_range * 0.79)
            ote_sweet = h_50 - (f_range * 0.705)
            inv_level = l_50
            target_level = h_50 + (f_range * 1.0) # Simple target: 1:1 extension
            
            if current > ote_high: # Price is still high, wait for OTE
                entry_zone = f"OTE Zone: {ote_low:.8f} - {ote_high:.8f} (Sweet: {ote_sweet:.8f})"
                invalidation = f"Below {l_50:.8f}"
            else: # Price is already in or below OTE
                entry_zone = f"Direct Buy (Inside Deep OTE) @ {current:.8f}"
                invalidation = f"Below {l_50:.8f}"

        # Target Potential (Rough estimate based on recent range)
        range_30d = max(c.high for c in candles[-30:]) - min(c.low for c in candles[-30:])
        potential = (range_30d / current) * 100
        target_str = f"~{potential:.1f}% Extension Potential"

        return InvestmentResult(
            symbol=symbol,
            score=min(score, 95.0),  # Cap at 95 — only ML-validated setups should ever be 100
            discovery_type=discovery_type,
            logic="; ".join(logic_details),
            target_potential=target_str,
            target_level=target_level,
            entry_zone=entry_zone,
            invalidation_level=invalidation,
            inv_level=inv_level,
            timestamp=candles[-1].timestamp,
            url=url,
            extra_metadata={
                "vpc_ratio": vpc_ratio,
                "rs_alpha": rs_alpha if "rs_alpha" in locals() else 0.0,
                "sector_alpha": sector_alpha if "sector_alpha" in locals() else 0.0,
                "market_sentiment": sentiment_bonus,
                "trend_orientation": trend[-1].direction if trend else "NEUTRAL",
                "vol_ratio": vol_ratio,
                "market_regime": regime
            }
        )

    def _find_liquidity(self, candles: List[Candle], pivots: List[Dict]) -> List[ICTPattern]:
        # (This remains unchanged but including for file integrity in replace_file_content)
        threshold = 0.0005 
        patterns = []
        for i in range(len(pivots)):
            for j in range(i + 1, len(pivots)):
                p1, p2 = pivots[i], pivots[j]
                if p1["type"] == p2["type"]:
                    diff = abs(p1["price"] - p2["price"]) / p1["price"]
                    if diff < threshold:
                        typ = "EQH" if p1["type"] == "HH" else "EQL"
                        patterns.append(ICTPattern(
                            type="Liquidity", direction="NEUTRAL",
                            price_range=(min(p1["price"], p2["price"]), max(p1["price"], p2["price"])),
                            strength=1.5, context=f"{typ} Pool",
                            timestamp=max(p1["timestamp"], p2["timestamp"])
                        ))
        return patterns
