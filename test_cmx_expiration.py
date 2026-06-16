import MetaTrader5 as mt5
import time
import os

def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

env = load_env()

path2 = "C:\\MT5_Broker2\\terminal64.exe"
login2 = int(env.get("MT5_LOGIN"))
pass2 = env.get("MT5_PASSWORD")
server2 = env.get("MT5_SERVER")

if mt5.initialize(path=path2, login=login2, password=pass2, server=server2):
    print("Connected to MTS")
    symbols = mt5.symbols_get(group="*CMX.MGC*")
    for s in symbols:
        print(f"{s.name}: Expiration = {s.expiration_time}")
    mt5.shutdown()
else:
    print("MTS Initialize Failed:", mt5.last_error())
