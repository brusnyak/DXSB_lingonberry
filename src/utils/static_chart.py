import os
import pandas as pd
import mplfinance as mpf
from typing import List
from ..analysis.ict_analyst import Candle, ICTPattern

def generate_static_chart(candles: List['Candle'], symbol: str, output_path: str = "chart.png") -> str:
    """Generates a static PNG chart suitable for Telegram media alerts."""
    
    if not candles:
        return ""

    data = []
    for c in candles:
        # Determine if timestamp is ms or s
        unit = 's' if c.timestamp < 1e10 else 'ms'
        data.append({
            "Date": pd.to_datetime(c.timestamp, unit=unit),
            "Open": c.open,
            "High": c.high,
            "Low": c.low,
            "Close": c.close,
            "Volume": c.volume
        })
    
    df = pd.DataFrame(data)
    df.set_index("Date", inplace=True)
    
    # Dark mode premium style
    mc = mpf.make_marketcolors(
        up='#26a69a', down='#ef5350', 
        edge='inherit', wick='inherit', 
        volume='in', ohlc='inherit'
    )
    s = mpf.make_mpf_style(
        marketcolors=mc, 
        base_mpf_style='nightclouds', 
        gridstyle=':',
        y_on_right=True,
        facecolor="#131722",
        edgecolor="#2B2B43",
        figcolor="#131722"
    )
    
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    try:
        # Add EMA 50 and 200
        ap0 = [mpf.make_addplot(df['Close'].ewm(span=50, adjust=False).mean(), color='#2962FF', width=1.0)]
        if len(df) >= 200:
            ap0.append(mpf.make_addplot(df['Close'].ewm(span=200, adjust=False).mean(), color='#FF9800', width=1.0))
            
        mpf.plot(
            df, 
            type='candle', 
            style=s, 
            title=f"\nInvestment Analysis: {symbol}", 
            volume=True,
            addplot=ap0,
            tight_layout=True,
            figsize=(10, 6),
            savefig=dict(fname=output_path, dpi=120, bbox_inches='tight', facecolor='#131722')
        )
        return output_path
    except Exception as e:
        print(f"Error generating static chart: {e}")
        return ""
