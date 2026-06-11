import MetaTrader5 as mt5
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def fetch_tick_data(login, password, server, exact_symbols, prefixes, account_name):
    if not mt5.initialize(login=login, password=password, server=server):
        print(f"Failed to initialize MT5 for account {login}")
        return

    print(f"\n--- Fetching tick data for Account: {account_name} ({login}) ---")
    
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

    date_from = datetime(2010, 1, 1) # Start from an old date
    date_to = datetime.now()

    for sym in target_symbols:
        if not mt5.symbol_select(sym, True):
            print(f"Could not select {sym}")
            continue
        
        print(f"Fetching tick data for {sym}...")
        ticks = mt5.copy_ticks_range(sym, date_from, date_to, mt5.COPY_TICKS_ALL)
        
        if ticks is None or len(ticks) == 0:
            print(f"{sym:<15}: No tick data found")
        else:
            df = pd.DataFrame(ticks)
            # convert time in seconds into the datetime format
            df['time_sec'] = pd.to_datetime(df['time'], unit='s')
            df['time_ms'] = pd.to_datetime(df['time_msc'], unit='ms')
            
            filename = f"historical_data/{sym}_ticks_{account_name}.csv"
            df.to_csv(filename, index=False)
            print(f"{sym:<15}: Fetched {len(df)} ticks. Saved to {filename}")

    mt5.shutdown()


if __name__ == "__main__":
    # Account 1
    login1 = int(os.environ.get("MT5_LOGIN"))
    pass1 = os.environ.get("MT5_PASSWORD")
    server1 = os.environ.get("MT5_SERVER")
    fetch_tick_data(
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
    fetch_tick_data(
        login=login2, 
        password=pass2, 
        server=server2, 
        exact_symbols=["UKOUSD.sc", "USOUSD.sc", "XAUUSD.sc"],
        prefixes=[],
        account_name="Vantage"
    )
