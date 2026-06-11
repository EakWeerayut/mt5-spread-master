import MetaTrader5 as mt5
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def fetch_h1_data(login, password, server, exact_symbols, prefixes, account_name):
    if not mt5.initialize(login=login, password=password, server=server):
        print(f"Failed to initialize MT5 for account {login}")
        return

    print(f"\n--- Fetching H1 data for Account: {account_name} ({login}) ---")
    
    os.makedirs('historical_data/tfx', exist_ok=True)

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

    for sym in target_symbols:
        if not mt5.symbol_select(sym, True):
            print(f"Could not select {sym}")
            continue
        
        print(f"Fetching H1 data for {sym}...")
        # Request 50000 bars
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
        
        if rates is None or len(rates) == 0:
            print(f"{sym:<15}: No historical data found")
        else:
            sym_info = mt5.symbol_info(sym)
            point = sym_info.point if sym_info else 0.00001
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df['bid'] = df['close']
            df['offer'] = df['close'] + (df['spread'] * point)
            
            df_final = df[['time', 'bid', 'offer']]
            
            filename = f"historical_data/tfx/{sym}_H1_{account_name}.csv"
            
            if os.path.exists(filename):
                df_old = pd.read_csv(filename)
                df_old['time'] = pd.to_datetime(df_old['time'])
                df_combined = pd.concat([df_old, df_final])
                df_combined = df_combined.drop_duplicates(subset=['time'], keep='last')
                df_combined = df_combined.sort_values('time')
                df_combined.to_csv(filename, index=False)
                print(f"{sym:<15}: Appended new data. Total H1 bars: {len(df_combined)}. Saved to {filename}")
            else:
                df_final.to_csv(filename, index=False)
                print(f"{sym:<15}: Fetched {len(df_final)} H1 bars. Saved to {filename}")

    mt5.shutdown()


if __name__ == "__main__":
    login3 = int(os.environ.get("MT5_LOGIN_3"))
    pass3 = os.environ.get("MT5_PASSWORD_3")
    server3 = os.environ.get("MT5_SERVER_3")
    fetch_h1_data(
        login=login3, 
        password=pass3, 
        server=server3, 
        exact_symbols=[], 
        prefixes=["TFX.S50"],
        account_name="MTS"
    )
