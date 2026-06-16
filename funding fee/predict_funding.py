import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error

def fetch_btc_price_data(start_time_ms, end_time_ms):
    print("Fetching BTCUSDT 8h klines from Binance...")
    url = "https://api.binance.com/api/v3/klines"
    all_klines = []
    current_start = start_time_ms
    
    while current_start < end_time_ms:
        params = {
            "symbol": "BTCUSDT",
            "interval": "8h",
            "startTime": current_start,
            "endTime": end_time_ms,
            "limit": 1000
        }
        try:
            res = requests.get(url, params=params)
            res.raise_for_status()
            data = res.json()
            if not data:
                break
            all_klines.extend(data)
            current_start = data[-1][0] + 1
            time.sleep(0.5)
        except Exception as e:
            print("Error fetching klines:", e)
            break
            
    df = pd.DataFrame(all_klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close'] = df['close'].astype(float)
    df.set_index('datetime', inplace=True)
    return df[['close']]

def build_model():
    # 1. Load Data
    df_b = pd.read_csv("binance_BTCUSDT_funding.csv", parse_dates=['datetime']).set_index('datetime')
    df_d = pd.read_csv("deribit_BTCUSD_funding.csv", parse_dates=['datetime']).set_index('datetime')
    
    df_d_8h = df_d['interest_1h'].resample('8h', offset='0h').sum().to_frame(name='deribit_rate')
    
    df = pd.DataFrame(index=df_b.index)
    df['binance_rate'] = df_b['fundingRate']
    df = df.join(df_d_8h['deribit_rate'], how='inner')
    df.dropna(inplace=True)
    
    # Calculate Spread (Binance - Deribit)
    df['spread'] = df['binance_rate'] - df['deribit_rate']
    
    # 2. Fetch Price Data
    start_ms = int(df.index.min().timestamp() * 1000)
    end_ms = int(df.index.max().timestamp() * 1000)
    df_price = fetch_btc_price_data(start_ms, end_ms)
    
    # Merge Price Data
    df = df.join(df_price, how='inner')
    
    # 3. Feature Engineering
    # We want to predict the spread at T+1 based on data up to T
    
    # Target: Next period's spread
    df['target_spread_t1'] = df['spread'].shift(-1)
    
    # Features
    df['spread_lag1'] = df['spread'].shift(1)
    df['spread_lag3'] = df['spread'].shift(3)
    df['btc_return_8h'] = df['close'].pct_change(1)
    df['btc_return_24h'] = df['close'].pct_change(3)
    df['btc_return_7d'] = df['close'].pct_change(21)
    
    # Volatility (Rolling standard deviation of returns)
    df['btc_volatility_7d'] = df['btc_return_8h'].rolling(21).std()
    
    # Binance Absolute Rate level
    df['binance_rate_lag1'] = df['binance_rate'].shift(1)
    
    df.dropna(inplace=True)
    
    # 4. Train Model
    features = ['spread_lag1', 'spread_lag3', 'btc_return_8h', 'btc_return_24h', 
                'btc_return_7d', 'btc_volatility_7d', 'binance_rate_lag1']
    
    X = df[features]
    y = df['target_spread_t1']
    
    # Train test split (temporal split to prevent look-ahead bias)
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    rf = RandomForestRegressor(n_estimators=100, max_depth=5, random_state=42)
    rf.fit(X_train, y_train)
    
    y_pred = rf.predict(X_test)
    
    # 5. Evaluate
    r2 = r2_score(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    
    print("\n--- Model Evaluation ---")
    print(f"R-squared Score: {r2:.4f}")
    print(f"Mean Absolute Error: {mae:.6f} (Annualized: {mae * 3 * 365 * 100:.2f}%)")
    
    print("\n--- Feature Importance ---")
    importances = pd.Series(rf.feature_importances_, index=features).sort_values(ascending=False)
    for feat, imp in importances.items():
        print(f"{feat:20}: {imp:.4f}")
        
    # Analyze correlations to answer "when is Binance more expensive?"
    corr_return = df['btc_return_24h'].corr(df['spread'])
    corr_vol = df['btc_volatility_7d'].corr(df['spread'])
    
    print("\n--- Key Findings ---")
    print(f"Correlation between BTC 24H Return and Funding Spread: {corr_return:.4f}")
    print(f"Correlation between BTC Volatility and Funding Spread: {corr_vol:.4f}")

if __name__ == "__main__":
    build_model()
