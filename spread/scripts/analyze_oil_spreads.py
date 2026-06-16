import pandas as pd

def analyze_oil_spreads():
    # Load NYX.MCLE Continuous (WTI Futures)
    try:
        nyx = pd.read_csv("historical_data/NYX.MCLE_Continuous_H1.csv")
        nyx['time'] = pd.to_datetime(nyx['time'])
        nyx['mid_nyx'] = nyx['NYX.MCLE']
    except Exception as e:
        print(f"Error loading NYX: {e}")
        return

    # Load USOUSD.sc (WTI Spot)
    try:
        uso = pd.read_csv("historical_data/USOUSD.sc_H1_Vantage.csv")
        uso['time'] = pd.to_datetime(uso['time'])
        uso['mid_uso'] = (uso['bid'] + uso['offer']) / 2
    except Exception as e:
        print(f"Error loading USO: {e}")
        return

    # Load UKOUSD.sc (Brent Spot)
    try:
        uko = pd.read_csv("historical_data/UKOUSD.sc_H1_Vantage.csv")
        uko['time'] = pd.to_datetime(uko['time'])
        uko['mid_uko'] = (uko['bid'] + uko['offer']) / 2
    except Exception as e:
        print(f"Error loading UKO: {e}")
        return

    # Merge NYX (Futures WTI) and USO (Spot WTI)
    merged_wti = pd.merge(nyx[['time', 'mid_nyx']], 
                          uso[['time', 'mid_uso']], 
                          on='time', how='inner')
                          
    if not merged_wti.empty:
        merged_wti['price_spread'] = merged_wti['mid_nyx'] - merged_wti['mid_uso']
        merged_wti['basis_pct'] = (merged_wti['price_spread'] / merged_wti['mid_uso']) * 100

        print("\n=== 1. WTI Price Spread: NYX.MCLE (Futures) vs USOUSD (Spot) ===")
        print(f"Total overlapping hours: {len(merged_wti)}")
        print(f"Mean Spread   : ${merged_wti['price_spread'].mean():.2f}")
        print(f"Median Spread : ${merged_wti['price_spread'].median():.2f}")
        print(f"Min Spread    : ${merged_wti['price_spread'].min():.2f}")
        print(f"Max Spread    : ${merged_wti['price_spread'].max():.2f}")
        print(f"Mean Basis    : {merged_wti['basis_pct'].mean():.3f}%")
        
        contango_pct = (merged_wti['price_spread'] > 0).mean() * 100
        print(f"Contango (Futures > Spot)      : {contango_pct:.2f}% of the time")
        print(f"Backwardation (Futures < Spot) : {100 - contango_pct:.2f}% of the time")
        
        merged_wti['month'] = merged_wti['time'].dt.to_period('M')
        monthly = merged_wti.groupby('month')['price_spread'].mean()
        print("[Monthly Average Spread]")
        for m, val in monthly.items():
            print(f"{m} : ${val:.2f}")
    else:
        print("No overlapping data for NYX vs USO.")

    # Merge UKO (Spot Brent) and USO (Spot WTI)
    merged_oil = pd.merge(uko[['time', 'mid_uko']], 
                          uso[['time', 'mid_uso']], 
                          on='time', how='inner')
                          
    if not merged_oil.empty:
        merged_oil['brent_wti_spread'] = merged_oil['mid_uko'] - merged_oil['mid_uso']

        print("\n=== 2. Brent-WTI Spread: UKOUSD (Brent) vs USOUSD (WTI) ===")
        print(f"Total overlapping hours: {len(merged_oil)}")
        print(f"Mean Spread   : ${merged_oil['brent_wti_spread'].mean():.2f}")
        print(f"Median Spread : ${merged_oil['brent_wti_spread'].median():.2f}")
        print(f"Min Spread    : ${merged_oil['brent_wti_spread'].min():.2f}")
        print(f"Max Spread    : ${merged_oil['brent_wti_spread'].max():.2f}")
        
        brent_premium_pct = (merged_oil['brent_wti_spread'] > 0).mean() * 100
        print(f"Brent is Premium to WTI : {brent_premium_pct:.2f}% of the time")
        
        merged_oil['month'] = merged_oil['time'].dt.to_period('M')
        monthly_oil = merged_oil.groupby('month')['brent_wti_spread'].mean()
        print("[Monthly Average Spread]")
        for m, val in monthly_oil.items():
            print(f"{m} : ${val:.2f}")
    else:
        print("No overlapping data for UKO vs USO.")

if __name__ == "__main__":
    analyze_oil_spreads()
