import pandas as pd
import numpy as np

def check_price_correlation():
    # Load data
    df_b = pd.read_csv("binance_BTCUSDT_funding.csv", parse_dates=['datetime']).set_index('datetime')
    df_d = pd.read_csv("deribit_BTCUSD_funding.csv", parse_dates=['datetime']).set_index('datetime')
    df_d_8h = df_d['interest_1h'].resample('8h', offset='0h').sum().to_frame(name='deribit_rate')
    
    df = pd.DataFrame(index=df_b.index)
    df['binance_rate'] = df_b['fundingRate']
    df = df.join(df_d_8h['deribit_rate'], how='inner')
    df.dropna(inplace=True)
    df['spread'] = df['binance_rate'] - df['deribit_rate']
    
    # Load Price
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
    df.dropna(inplace=True)
    
    corr_price = df['close'].corr(df['spread'])
    
    # Let's bin the prices into percentiles to see the average spread
    df['price_bin'] = pd.qcut(df['close'], q=4, labels=["Low", "Medium", "High", "Very High"])
    
    print("\n--- BTC Price vs Spread (Binance USDT - Deribit) ---")
    print(f"Correlation between Absolute BTC Price and Spread: {corr_price:.4f}")
    
    print("\nAverage Spread by BTC Price Level (Annualized):")
    grouped = df.groupby('price_bin', observed=False)['spread'].mean() * 3 * 365 * 100
    for name, val in grouped.items():
        print(f"Price {name:>9}: {val:6.2f}%")
        
    # How about BTC market regime? e.g. < $30k vs > $60k
    df['price_range'] = pd.cut(df['close'], bins=[0, 30000, 60000, 100000], labels=["< $30k", "$30k-$60k", "> $60k"])
    grouped_range = df.groupby('price_range', observed=False)['spread'].mean() * 3 * 365 * 100
    print("\nAverage Spread by Exact Price Range (Annualized):")
    for name, val in grouped_range.items():
        print(f"{name:>10}: {val:6.2f}%")

if __name__ == "__main__":
    check_price_correlation()
