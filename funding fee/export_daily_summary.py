import pandas as pd
import numpy as np
import requests
from datetime import datetime, timezone

def export_daily():
    print("Loading funding data...")
    df_b_usdt = pd.read_csv("binance_BTCUSDT_funding.csv", parse_dates=['datetime']).set_index('datetime')
    df_b_usdc = pd.read_csv("binance_BTCUSDC_funding.csv", parse_dates=['datetime']).set_index('datetime')
    df_d = pd.read_csv("deribit_BTCUSD_funding.csv", parse_dates=['datetime']).set_index('datetime')
    
    # Deribit is 1H. Resample to Daily (Sum of 1H rates = Daily Rate)
    # Then multiply by 365 * 100 for Annualized %
    daily_d = df_d['interest_1h'].resample('1D').sum() * 365 * 100
    
    # Binance is 8H. Resample to Daily (Sum of 3 8H rates = Daily Rate)
    daily_b_usdt = df_b_usdt['fundingRate'].resample('1D').sum() * 365 * 100
    daily_b_usdc = df_b_usdc['fundingRate'].resample('1D').sum() * 365 * 100
    
    # Fetch Daily BTC Price from Binance
    print("Fetching Daily BTC Price...")
    url = "https://api.binance.com/api/v3/klines"
    all_klines = []
    # Use the earliest date
    start_ms = int(daily_b_usdt.index.min().timestamp() * 1000)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    current_start = start_ms
    while current_start < end_ms:
        params = {"symbol": "BTCUSDT", "interval": "1d", "startTime": current_start, "endTime": end_ms, "limit": 1000}
        res = requests.get(url, params=params)
        data = res.json()
        if not data: break
        all_klines.extend(data)
        current_start = data[-1][0] + 1
        
    df_price = pd.DataFrame(all_klines, columns=['open_time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'nt', 'tbbav', 'tbqav', 'ignore'])
    df_price['datetime'] = pd.to_datetime(df_price['open_time'], unit='ms')
    df_price['BTC_Price'] = df_price['close'].astype(float)
    daily_price = df_price.set_index('datetime')['BTC_Price']
    
    # Merge all
    df_final = pd.DataFrame(index=daily_b_usdt.index)
    df_final['Binance_USDT_APY_%'] = daily_b_usdt.round(2)
    df_final = df_final.join(daily_b_usdc.rename('Binance_USDC_APY_%').round(2), how='left')
    df_final = df_final.join(daily_d.rename('Deribit_BTC_APY_%').round(2), how='left')
    df_final = df_final.join(daily_price.round(2), how='left')
    
    # Format the index
    df_final.index.name = 'Date'
    df_final.reset_index(inplace=True)
    df_final['Date'] = df_final['Date'].dt.date
    
    # Drop rows where everything is NaN (shouldn't happen)
    df_final.dropna(subset=['Binance_USDT_APY_%', 'Deribit_BTC_APY_%', 'BTC_Price'], how='all', inplace=True)
    
    out_file = "daily_funding_summary.csv"
    df_final.to_csv(out_file, index=False)
    print(f"Exported {len(df_final)} days of data to {out_file}")

if __name__ == "__main__":
    export_daily()
