import json
import os
from typing import List, Dict
from src.analysis.ict_analyst import Candle, ICTPattern

class ICTVisualizer:
    """Generates interactive HTML charts with ICT pattern overlays (BOS, CHoCH, EMAs)."""
    
    HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Investment Brief - {symbol}</title>
    <script>
    {js_library}
    </script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #131722; color: #d1d4dc; margin: 0; padding: 20px; }
        #chart { height: 600px; width: 100%; border: 1px solid #2B2B43; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .badge { padding: 4px 12px; border-radius: 4px; font-size: 14px; font-weight: bold; }
        .score-badge { font-size: 24px; padding: 10px 20px; border: 2px solid #26a69a; color: #26a69a; border-radius: 8px; }
        .bullish { background: #26a69a; color: white; }
        .bearish { background: #ef5350; color: white; }
        .neutral { background: #787b86; color: white; }
        .logic-card { background: #1e222d; padding: 15px; border-radius: 8px; margin-top: 20px; border-left: 4px solid #2962FF; }
        .legend { display: flex; gap: 15px; margin-top: 10px; font-size: 12px; }
        .legend-item { display: flex; align-items: center; gap: 5px; }
        .dot { width: 10px; height: 10px; border-radius: 50%; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Strategic Investment Brief: {symbol}</h1>
            <div style="margin-top: -10px;"><span class="badge neutral">{adapter}</span></div>
        </div>
        <div class="score-badge">SCORE: {investment_score}</div>
    </div>

    <div id="chart"></div>
    
    <div class="logic-card">
        <h3>Investment Discovery Logic ({discovery_type}):</h3>
        <p>{investment_logic}</p>
        <p style="color: #26a69a; font-weight: bold;">{target_potential}</p>
    </div>

    <div class="legend">
        <div class="legend-item"><div class="dot" style="background:#2962FF"></div> EMA 50</div>
        <div class="legend-item"><div class="dot" style="background:#FF9800"></div> EMA 200</div>
        <div class="legend-item"><div class="dot" style="background:#26a69a"></div> Bullish BOS/CHoCH</div>
        <div class="legend-item"><div class="dot" style="background:#ef5350"></div> Bearish BOS/CHoCH</div>
    </div>

    <div style="margin-top: 20px;">
        <h3>Market Structure & Evidence:</h3>
        <ul id="pattern-list"></ul>
    </div>

    <script>
        window.onload = function() {
            if (typeof LightweightCharts === 'undefined') {
                document.getElementById('chart').innerHTML = '<h2>Error: Charts failed to load.</h2>';
                return;
            }

            const chart = LightweightCharts.createChart(document.getElementById('chart'), {
                width: document.getElementById('chart').offsetWidth,
                height: 600,
                layout: { background: { type: 'solid', color: '#131722' }, textColor: '#d1d4dc' },
                grid: { vertLines: { color: '#2B2B43' }, horzLines: { color: '#2B2B43' } },
                crosshair: { mode: 0 },
                priceScale: { borderColor: '#485c7b' },
                timeScale: { borderColor: '#485c7b', timeVisible: true },
            });
            const candleSeries = chart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderVisible: false });
            candleSeries.setData({candles_json});

            // Add EMAs
            const ema50Data = {ema50_json};
            if (ema50Data.length > 0) {
                const ema50Line = chart.addLineSeries({ color: '#2962FF', lineWidth: 1, title: 'EMA 50' });
                ema50Line.setData(ema50Data);
            }
            const ema200Data = {ema200_json};
            if (ema200Data.length > 0) {
                const ema200Line = chart.addLineSeries({ color: '#FF9800', lineWidth: 1, title: 'EMA 200' });
                ema200Line.setData(ema200Data);
            }

            const patterns = {patterns_json};
            const list = document.getElementById('pattern-list');
            const markers = [];

            patterns.forEach(p => {
                const li = document.createElement('li');
                li.innerHTML = `<b>${p.type}</b> (${p.direction}) - ${p.context}`;
                list.appendChild(li);

                let shape = 'circle';
                let color = p.direction === 'BULLISH' ? '#26a69a' : (p.direction === 'BEARISH' ? '#ef5350' : '#787b86');
                if (['CHoCH', 'BOS'].includes(p.type)) shape = 'arrowUp';
                
                markers.push({
                    time: p.timestamp,
                    position: p.direction === 'BULLISH' ? 'belowBar' : 'aboveBar',
                    color: color,
                    shape: shape,
                    text: p.type,
                });
            });

            candleSeries.setMarkers(markers.sort((a,b) => a.time - b.time));
        };
    </script>
</body>
</html>
"""

    def generate_report(self, candles: List[Candle], patterns: List[ICTPattern], symbol: str, adapter: str, output_path: str = "ict_report.html", investment_result=None):
        # Load local JS library
        js_library = ""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        lib_path = os.path.join(base_dir, "assets", ".lightweight-charts.js")
        if os.path.exists(lib_path):
            with open(lib_path, "r") as f: js_library = f.read()
            
        candles_data = [{"time": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in candles]
        
        # Calculate EMAs for visualization
        ema50 = self._calculate_ema(candles, 50)
        ema200 = self._calculate_ema(candles, 200)
        
        ema50_data = [{"time": candles[i].timestamp, "value": ema50[i-50+1]} for i in range(50-1, len(candles))]
        ema200_data = [{"time": candles[i].timestamp, "value": ema200[i-200+1]} for i in range(200-1, len(candles))]

        patterns_data = [{
            "type": p.type, "direction": p.direction, "context": p.context,
            "timestamp": p.timestamp if p.timestamp else candles[-1].timestamp
        } for p in patterns]

        html = self.HTML_TEMPLATE.replace("{symbol}", symbol)
        html = html.replace("{adapter}", adapter)
        html = html.replace("{candles_json}", json.dumps(candles_data))
        html = html.replace("{ema50_json}", json.dumps(ema50_data))
        html = html.replace("{ema200_json}", json.dumps(ema200_data))
        html = html.replace("{patterns_json}", json.dumps(patterns_data))
        html = html.replace("{js_library}", js_library)

        if investment_result:
            html = html.replace("{investment_score}", f"{investment_result.score:.1f}")
            html = html.replace("{discovery_type}", investment_result.discovery_type)
            html = html.replace("{investment_logic}", investment_result.logic)
            html = html.replace("{target_potential}", investment_result.target_potential)
        else:
            html = html.replace("{investment_score}", "N/A")
            html = html.replace("{discovery_type}", "Trading")
            html = html.replace("{investment_logic}", "Standard Market Analysis")
            html = html.replace("{target_potential}", "N/A")
        
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f: f.write(html)
        print(f"Report generated: {output_path}")
        return output_path

    def _calculate_ema(self, candles: List[Candle], period: int) -> List[float]:
        if len(candles) < period: return []
        closes = [c.close for c in candles]
        ema = []
        k = 2 / (period + 1)
        sma = sum(closes[:period]) / period
        ema.append(sma)
        for i in range(period, len(closes)):
            ema.append((closes[i] * k) + (ema[-1] * (1 - k)))
        return ema
