import MetaTrader5 as mt5
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def fetch_historical_data(login, password, server, exact_symbols, prefixes, account_name):
    if not mt5.initialize(login=login, password=password, server=server):
        print(f"Failed to initialize MT5 for account {login}")
        return

    print(f"\n--- Fetching historical data for Account: {account_name} ({login}) ---")
    
    # Create directory if it doesn't exist
    os.makedirs('historical_data', exist_ok=True)

    all_symbols = mt5.symbols_get()
    if all_symbols is None:
        print("Failed to get symbols")
        mt5.shutdown()
        return

    target_symbols = []
    for sym in all_symbols:
        name = sym.name
        if name in exact_symbols:
            target_symbols.append(name)
        else:
            for prefix in prefixes:
                if name.startswith(prefix):
                    target_symbols.append(name)

    target_symbols = list(set(target_symbols))
    target_symbols.sort()

    # We will fetch D1 (Daily) data from 1970 to now
    timezone = mt5.terminal_info().timezone if mt5.terminal_info() is not None else 0
    date_from = datetime(1970, 1, 1)
    date_to = datetime.now()

    for sym in target_symbols:
        if not mt5.symbol_select(sym, True):
            print(f"Could not select {sym}")
            continue
        
        # Fetch data
        rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_D1, date_from, date_to)
        
        if rates is None or len(rates) == 0:
            print(f"{sym:<15}: No historical data found")
        else:
            # create DataFrame
            df = pd.DataFrame(rates)
            # convert time in seconds into the datetime format
            df['time'] = pd.to_datetime(df['time'], unit='s')
            
            filename = f"historical_data/{sym}_D1_{account_name}.csv"
            df.to_csv(filename, index=False)
            print(f"{sym:<15}: Fetched {len(df)} days of data. Saved to {filename}")

    mt5.shutdown()


if __name__ == "__main__":
    # Account 1
    login1 = int(os.environ.get("MT5_LOGIN"))
    pass1 = os.environ.get("MT5_PASSWORD")
    server1 = os.environ.get("MT5_SERVER")
    fetch_historical_data(
        login=login1, 
        password=pass1, 
        server=server1, 
        exact_symbols=[], 
        prefixes=["CMX.MGC", "NYX.MCLE"],
        account_name="MTS"
    )

    # Account 2
    login2 = int(os.environ.get("MT5_LOGIN_2"))
    pass2 = os.environ.get("MT5_PASSWORD_2")
    server2 = os.environ.get("MT5_SERVER_2")
    fetch_historical_data(
        login=login2, 
        password=pass2, 
        server=server2, 
        exact_symbols=["UKOUSD.sc", "USOUSD.sc", "XAUUSD.sc"], # Removed XAGUSD.sc
        prefixes=[],
        account_name="Vantage"
    )

