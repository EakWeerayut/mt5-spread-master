import MetaTrader5 as mt5
import os
from dotenv import load_dotenv

load_dotenv()

login1 = int(os.environ.get("MT5_LOGIN"))
pass1 = os.environ.get("MT5_PASSWORD")
server1 = os.environ.get("MT5_SERVER")

if not mt5.initialize(login=login1, password=pass1, server=server1):
    print("Initialize failed, error code =", mt5.last_error())
    quit()

print("--- Checking CMX.MGC ---")
cmx_symbols = mt5.symbols_get(group="*CMX.MGC*")
if cmx_symbols:
    for s in cmx_symbols:
        print(s.name)
else:
    print("No CMX.MGC symbols found")

print("\n--- Checking NYX.MCLE ---")
nyx_symbols = mt5.symbols_get(group="*NYX.MCLE*")
if nyx_symbols:
    for s in nyx_symbols:
        print(s.name)
else:
    print("No NYX.MCLE symbols found")

mt5.shutdown()
