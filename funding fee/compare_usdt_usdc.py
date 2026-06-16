import pandas as pd
import numpy as np

def compare_usdt_usdc():
    df_usdt = pd.read_csv("binance_BTCUSDT_funding.csv", parse_dates=['datetime']).set_index('datetime')
    df_usdc = pd.read_csv("binance_BTCUSDC_funding.csv", parse_dates=['datetime']).set_index('datetime')
    
    # Merge on matching times
    df = pd.DataFrame(index=df_usdt.index)
    df['rate_usdt'] = df_usdt['fundingRate']
    df = df.join(df_usdc['fundingRate'].rename('rate_usdc'), how='inner')
    
    df['spread'] = df['rate_usdt'] - df['rate_usdc']
    
    # Load price data (from predict_funding.py's price fetch if possible, or just use binance api again)
    import requests
    url = "https://api.binance.com/api/v3/klines"
    all_klines = []
    start_ms = int(df.index.min().timestamp() * 1000)
    end_ms = int(df.index.max().timestamp() * 1000)
    
    current_start = start_ms
    while current_start < end_ms:
        params = {"symbol": "BTCUSDT", "interval": "8h", "startTime": current_start, "endTime": end_ms, "limit": 1000}
        res = requests.get(url, params=params)
        data = res.json()
        if not data: break
        all_klines.extend(data)
        current_start = data[-1][0] + 1
        
    df_price = pd.DataFrame(all_klines, columns=['open_time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'nt', 'tbbav', 'tbqav', 'ignore'])
    df_price['datetime'] = pd.to_datetime(df_price['open_time'], unit='ms')
    df_price['close'] = df_price['close'].astype(float)
    df_price.set_index('datetime', inplace=True)
    
    df = df.join(df_price[['close']], how='inner')
    
    # Features
    df['btc_return_24h'] = df['close'].pct_change(3)
    df['btc_volatility_7d'] = df['close'].pct_change(1).rolling(21).std()
    
    # Drop na
    df.dropna(inplace=True)
    
    corr_return = df['btc_return_24h'].corr(df['spread'])
    corr_vol = df['btc_volatility_7d'].corr(df['spread'])
    
    print("\n--- Binance USDT vs Binance USDC Analysis (Since 2024) ---")
    print(f"Data points: {len(df)} 8H periods")
    print(f"Mean Spread (USDT - USDC): {df['spread'].mean() * 3 * 365 * 100:.2f}% Annualized")
    print(f"Max Spread (USDT - USDC): {df['spread'].max() * 3 * 365 * 100:.2f}% Annualized")
    print(f"Min Spread (USDT - USDC): {df['spread'].min() * 3 * 365 * 100:.2f}% Annualized")
    print(f"Correlation with BTC 24H Return: {corr_return:.4f}")
    print(f"Correlation with BTC Volatility (7d): {corr_vol:.4f}")

if __name__ == "__main__":
    compare_usdt_usdc()
