import pandas as pd
import numpy as np

def analyze_spreads():
    # Load CMX.MGC Continuous
    try:
        cmx = pd.read_csv("historical_data/CMX.MGC_Continuous_H1.csv")
        cmx['time'] = pd.to_datetime(cmx['time'])
        cmx['spread_value'] = cmx['offer'] - cmx['bid']
        cmx['spread_bps'] = (cmx['spread_value'] / cmx['bid']) * 10000
    except Exception as e:
        print(f"Error loading CMX: {e}")
        return

    # Load XAUUSD.sc
    try:
        xau = pd.read_csv("historical_data/XAUUSD.sc_H1_Vantage.csv")
        xau['time'] = pd.to_datetime(xau['time'])
        xau['spread_value'] = xau['offer'] - xau['bid']
        xau['spread_bps'] = (xau['spread_value'] / xau['bid']) * 10000
    except Exception as e:
        print(f"Error loading XAU: {e}")
        return

    # Align them by time to compare apples to apples
    merged = pd.merge(cmx[['time', 'bid', 'offer', 'spread_value', 'spread_bps']], 
                      xau[['time', 'bid', 'offer', 'spread_value', 'spread_bps']], 
                      on='time', 
                      suffixes=('_cmx', '_xau'))

    if merged.empty:
        print("No overlapping time data found between CMX and XAU.")
        return

    print("--- Spread Analysis: CMX.MGC (Futures) vs XAUUSD.sc (Spot) ---")
    print(f"Total overlapping hours analyzed: {len(merged)}")
    
    print("\n[Absolute Spread ($/oz)]")
    print("CMX Mean : ${:.2f}".format(merged['spread_value_cmx'].mean()))
    print("XAU Mean : ${:.2f}".format(merged['spread_value_xau'].mean()))
    
    print("CMX Median : ${:.2f}".format(merged['spread_value_cmx'].median()))
    print("XAU Median : ${:.2f}".format(merged['spread_value_xau'].median()))
    
    print("CMX Max : ${:.2f}".format(merged['spread_value_cmx'].max()))
    print("XAU Max : ${:.2f}".format(merged['spread_value_xau'].max()))
    
    print("\n[Spread in Basis Points (bps)]")
    print("CMX Mean : {:.2f} bps".format(merged['spread_bps_cmx'].mean()))
    print("XAU Mean : {:.2f} bps".format(merged['spread_bps_xau'].mean()))
    
    print("\n[Comparison]")
    # How often is CMX wider than XAU?
    merged['cmx_wider'] = merged['spread_value_cmx'] > merged['spread_value_xau']
    cmx_wider_pct = merged['cmx_wider'].mean() * 100
    print(f"CMX Spread is wider than XAU {cmx_wider_pct:.2f}% of the time.")

if __name__ == "__main__":
    analyze_spreads()
