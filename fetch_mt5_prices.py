import MetaTrader5 as mt5
import os
from dotenv import load_dotenv

load_dotenv()

def get_prices_for_account(login, password, server):
    if not mt5.initialize(login=login, password=password, server=server):
        print(f"Failed to initialize MT5 for account {login}")
        return

    print(f"\n--- Account: {login} ({server}) ---")

    # Symbols to fetch exactly
    exact_symbols = ["UKOUSD.sc", "USOUSD.sc", "XAGUSD.sc", "XAUUSD.sc"]
    
    # Prefixes to search for series
    prefixes = ["CMX.MGC", "NYX.MCLE"]
    
    # Get all symbols
    all_symbols = mt5.symbols_get()
    if all_symbols is None:
        print("Failed to get symbols")
        mt5.shutdown()
        return

    # Filter symbols
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
        # Select symbol
        if not mt5.symbol_select(sym, True):
            continue
        
        info = mt5.symbol_info_tick(sym)
        if info is not None:
            print(f"{sym:<15} Bid: {info.bid:<10} Offer: {info.ask:<10}")
        else:
            print(f"{sym:<15} Data not available")

    mt5.shutdown()


if __name__ == "__main__":
    # Account 1
    login1 = int(os.environ.get("MT5_LOGIN"))
    pass1 = os.environ.get("MT5_PASSWORD")
    server1 = os.environ.get("MT5_SERVER")
    get_prices_for_account(login1, pass1, server1)

    # Account 2
    login2 = int(os.environ.get("MT5_LOGIN_2"))
    pass2 = os.environ.get("MT5_PASSWORD_2")
    server2 = os.environ.get("MT5_SERVER_2")
    get_prices_for_account(login2, pass2, server2)

