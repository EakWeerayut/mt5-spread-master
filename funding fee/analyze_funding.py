import pandas as pd
import numpy as np

def analyze():
    print("Loading data...")
    df_b_usdt = pd.read_csv("binance_BTCUSDT_funding.csv", parse_dates=['datetime'])
    df_b_usdc = pd.read_csv("binance_BTCUSDC_funding.csv", parse_dates=['datetime'])
    df_d = pd.read_csv("deribit_BTCUSD_funding.csv", parse_dates=['datetime'])
    
    # Set index
    df_b_usdt.set_index('datetime', inplace=True)
    df_b_usdc.set_index('datetime', inplace=True)
    df_d.set_index('datetime', inplace=True)
    
    # Deribit is continuous (hourly data). To compare with Binance (8H), we sum Deribit's 1h interest over the 8H period leading up to the Binance funding time.
    # Binance funding is at 00:00, 08:00, 16:00. 
    # Resample Deribit to 8H, ending at those times.
    df_d_8h = df_d['interest_1h'].resample('8h', offset='0h').sum().to_frame(name='deribit_rate')
    
    # Merge datasets
    df = pd.DataFrame(index=df_b_usdt.index)
    df['binance_usdt'] = df_b_usdt['fundingRate']
    df = df.join(df_b_usdc['fundingRate'].rename('binance_usdc'), how='left')
    df = df.join(df_d_8h['deribit_rate'], how='left')
    
    df.dropna(subset=['binance_usdt', 'deribit_rate'], inplace=True)
    
    # Calculate spreads
    # If Binance > Deribit, we can Short Binance (receive Binance rate) and Long Deribit (pay Deribit rate)
    # Profit = Binance Rate - Deribit Rate
    df['spread_usdt_deribit'] = df['binance_usdt'] - df['deribit_rate']
    
    # Same for USDC
    df_usdc = df.dropna(subset=['binance_usdc']).copy()
    df_usdc['spread_usdc_deribit'] = df_usdc['binance_usdc'] - df_usdc['deribit_rate']
    
    # Annualized yield calculation (Rate per 8H * 3 * 365 * 100 for %)
    annualized_multiplier = 3 * 365 * 100
    
    print("\n--- Funding Rate Arbitrage Analysis ---")
    print(f"Data period (USDT/Deribit): {df.index.min()} to {df.index.max()} ({len(df)} 8H periods)")
    
    print("\n[Average Annualized Rates]")
    print(f"Binance USDT : {df['binance_usdt'].mean() * annualized_multiplier:.2f}%")
    print(f"Deribit      : {df['deribit_rate'].mean() * annualized_multiplier:.2f}%")
    if not df_usdc.empty:
        print(f"Binance USDC : {df_usdc['binance_usdc'].mean() * annualized_multiplier:.2f}% (since {df_usdc.index.min()})")
        
    print("\n[Arbitrage Strategy: Short Binance USDT + Long Deribit]")
    mean_spread_usdt = df['spread_usdt_deribit'].mean() * annualized_multiplier
    print(f"Mean Annualized Profit : {mean_spread_usdt:.2f}%")
    print(f"Max 8H Profit (Ann.)   : {df['spread_usdt_deribit'].max() * annualized_multiplier:.2f}%")
    print(f"Min 8H Profit (Ann.)   : {df['spread_usdt_deribit'].min() * annualized_multiplier:.2f}%")
    positive_periods = (df['spread_usdt_deribit'] > 0).mean() * 100
    print(f"% of Time Profitable   : {positive_periods:.2f}%")
    
    if not df_usdc.empty:
        print("\n[Arbitrage Strategy: Short Binance USDC + Long Deribit]")
        mean_spread_usdc = df_usdc['spread_usdc_deribit'].mean() * annualized_multiplier
        print(f"Mean Annualized Profit : {mean_spread_usdc:.2f}%")
        print(f"Max 8H Profit (Ann.)   : {df_usdc['spread_usdc_deribit'].max() * annualized_multiplier:.2f}%")
        print(f"Min 8H Profit (Ann.)   : {df_usdc['spread_usdc_deribit'].min() * annualized_multiplier:.2f}%")
        positive_periods_usdc = (df_usdc['spread_usdc_deribit'] > 0).mean() * 100
        print(f"% of Time Profitable   : {positive_periods_usdc:.2f}%")
        
    # Analysis on raw Binance USDT vs Binance USDC
    if not df_usdc.empty:
        df_usdc['spread_usdt_usdc'] = df_usdc['binance_usdt'] - df_usdc['binance_usdc']
        print("\n[Arbitrage Strategy: Short Binance USDT + Long Binance USDC]")
        mean_spread_bin = df_usdc['spread_usdt_usdc'].mean() * annualized_multiplier
        print(f"Mean Annualized Profit : {mean_spread_bin:.2f}%")

if __name__ == "__main__":
    analyze()
