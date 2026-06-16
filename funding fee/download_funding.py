import requests
import pandas as pd
import time
from datetime import datetime, timezone

def download_binance_funding(symbol="BTCUSDT"):
    print(f"Downloading Binance {symbol} funding rates...")
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    all_data = []
    
    # Start from 2020-01-01 (BTCUSDC will just naturally break and return data from 2024)
    start_time = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    
    while True:
        params = {
            "symbol": symbol,
            "startTime": start_time,
            "limit": 1000
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                break
                
            all_data.extend(data)
            
            # The last element's fundingTime + 1ms becomes the new start_time
            last_time = data[-1]['fundingTime']
            if len(data) < 1000:
                break
            
            start_time = last_time + 1
            time.sleep(0.5) # respect rate limits
        except Exception as e:
            print(f"Error fetching Binance {symbol} data: {e}")
            break
            
    if all_data:
        df = pd.DataFrame(all_data)
        df['datetime'] = pd.to_datetime(df['fundingTime'], unit='ms')
        df.to_csv(f"binance_{symbol}_funding.csv", index=False)
        print(f"Saved {len(df)} rows to binance_{symbol}_funding.csv")

def download_deribit_funding():
    print("Downloading Deribit BTC-PERPETUAL funding rates...")
    url = "https://www.deribit.com/api/v2/public/get_funding_rate_history"
    all_data = []
    instrument_name = "BTC-PERPETUAL"
    
    # Start from 2019-01-01 (or as far back as it goes)
    current_start = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    final_end = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    while current_start < final_end:
        # Fetch 30 days at a time
        current_end = current_start + (30 * 24 * 60 * 60 * 1000)
        if current_end > final_end:
            current_end = final_end
            
        params = {
            "instrument_name": instrument_name,
            "start_timestamp": current_start,
            "end_timestamp": current_end
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'result' in data and data['result']:
                result_data = data['result']
                all_data.extend(result_data)
                
            current_start = current_end + 1
            time.sleep(0.5)
        except Exception as e:
            print(f"Error fetching Deribit data: {e}")
            break

    if all_data:
        df = pd.DataFrame(all_data)
        # Drop duplicates in case of overlap
        df.drop_duplicates(subset=['timestamp'], inplace=True)
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.to_csv("deribit_BTCUSD_funding.csv", index=False)
        print(f"Saved {len(df)} rows to deribit_BTCUSD_funding.csv")

if __name__ == "__main__":
    download_binance_funding("BTCUSDT")
    download_binance_funding("BTCUSDC")
    download_deribit_funding()
