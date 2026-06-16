import pandas as pd
import numpy as np

def analyze_price_spread():
    # Load CMX.MGC Continuous
    try:
        cmx = pd.read_csv("historical_data/CMX.MGC_Continuous_H1.csv")
        cmx['time'] = pd.to_datetime(cmx['time'])
        if 'bid' in cmx.columns and 'offer' in cmx.columns:
            cmx['mid_cmx'] = (cmx['bid'] + cmx['offer']) / 2
        elif 'CMX.MGC' in cmx.columns:
            cmx['mid_cmx'] = cmx['CMX.MGC']
        else:
            cmx['mid_cmx'] = cmx['price']
    except Exception as e:
        print(f"Error loading CMX: {e}")
        return

    # Load XAUUSD.sc
    try:
        xau = pd.read_csv("historical_data/XAUUSD.sc_H1_Vantage.csv")
        xau['time'] = pd.to_datetime(xau['time'])
        xau['mid_xau'] = (xau['bid'] + xau['offer']) / 2
    except Exception as e:
        print(f"Error loading XAU: {e}")
        return

    # Align them by time
    merged = pd.merge(cmx[['time', 'mid_cmx']], 
                      xau[['time', 'mid_xau']], 
                      on='time', how='inner')

    if merged.empty:
        print("No overlapping time data found between CMX and XAU.")
        return

    # Calculate Price Spread (Futures - Spot)
    merged['price_spread'] = merged['mid_cmx'] - merged['mid_xau']
    
    # Calculate % Spread (Basis)
    merged['basis_pct'] = (merged['price_spread'] / merged['mid_xau']) * 100

    print("--- Price Spread Analysis: CMX.MGC (Futures) vs XAUUSD (Spot) ---")
    print(f"Total overlapping hours analyzed: {len(merged)}")
    print(f"Date Range: {merged['time'].min()} to {merged['time'].max()}")
    
    print("\n[Absolute Price Spread ($/oz)]")
    print(f"Mean Spread   : ${merged['price_spread'].mean():.2f}")
    print(f"Median Spread : ${merged['price_spread'].median():.2f}")
    print(f"Min Spread    : ${merged['price_spread'].min():.2f}")
    print(f"Max Spread    : ${merged['price_spread'].max():.2f}")
    print(f"Std Dev       : ${merged['price_spread'].std():.2f}")

    print("\n[Spread in % (Basis)]")
    print(f"Mean Basis    : {merged['basis_pct'].mean():.3f}%")
    
    # Check Contango vs Backwardation
    contango_pct = (merged['price_spread'] > 0).mean() * 100
    print(f"\nContango (Futures > Spot)      : {contango_pct:.2f}% of the time")
    print(f"Backwardation (Futures < Spot) : {100 - contango_pct:.2f}% of the time")
    
    # See how it changes over time by taking the mean per month
    merged['month'] = merged['time'].dt.to_period('M')
    monthly = merged.groupby('month')['price_spread'].mean()
    print("\n[Monthly Average Spread]")
    for m, val in monthly.items():
        print(f"{m} : ${val:.2f}")

if __name__ == "__main__":
    analyze_price_spread()
