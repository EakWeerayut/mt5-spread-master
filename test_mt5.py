import MetaTrader5 as mt5
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

login2 = int(os.environ.get("MT5_LOGIN_2"))
pass2 = os.environ.get("MT5_PASSWORD_2")
server2 = os.environ.get("MT5_SERVER_2")

if not mt5.initialize(login=login2, password=pass2, server=server2):
    print("Initialize failed, error code =", mt5.last_error())
    quit()

sym = "XAUUSD.sc"
mt5.symbol_select(sym, True)

# Try getting 1000 bars
rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 1000)

if rates is None:
    print(f"Failed to get rates, error code =", mt5.last_error())
else:
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    print("Success! Fetched", len(df), "bars")
    print(df.head())

mt5.shutdown()
