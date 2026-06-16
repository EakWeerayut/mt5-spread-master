import os
import json
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()
api_key = os.getenv("BINANCE_API_KEY", "").strip()
api_secret = os.getenv("BINANCE_API_SECRET", "").strip()

client = Client(api_key, api_secret)

import time
server_time = client.get_server_time()
local_time = int(time.time() * 1000)
client.timestamp_offset = server_time['serverTime'] - local_time

# Fetch recent deposits
deposits = client.get_deposit_history(coin='BTC')
print("BTC Deposits:", deposits[:2])

# Fetch spot trades
trades = client.get_my_trades(symbol='BTCUSDT', limit=5)
print("BTCUSDT Spot Trades:", trades)

# Fetch futures income
income = client.futures_income_history(symbol='BTCUSDT', limit=5)
print("BTCUSDT Futures Income:", income)
