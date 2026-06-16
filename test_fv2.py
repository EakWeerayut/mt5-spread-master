import json, os, time

symbol1 = "CMX.MGC07"
symbol2 = "XAUUSD.sc"

cmx_sym = None
oil_sym = None

if symbol1 and symbol1.startswith("CMX.MGC") and symbol2 == "XAUUSD.sc":
    cmx_sym = symbol1
elif symbol2 and symbol2.startswith("CMX.MGC") and symbol1 == "XAUUSD.sc":
    cmx_sym = symbol2

print(f"symbol1={repr(symbol1)}, symbol2={repr(symbol2)}")
print(f"cmx_sym={cmx_sym}")

fv_m = None
fv_c = None
fv_exp = 0

if cmx_sym:
    try:
        if os.path.exists("historical_data/cmx/meta.json"):
            with open("historical_data/cmx/meta.json", "r") as f:
                meta = json.load(f)
            print(f"meta keys: {list(meta.keys())}")
            if cmx_sym in meta:
                fv_exp = meta[cmx_sym].get("expiration_time", 0)
                print(f"Exact key match: fv_exp={fv_exp}")
            else:
                now_ts = time.time()
                future = {k: v["expiration_time"] for k, v in meta.items() if v.get("expiration_time", 0) > now_ts}
                print(f"No exact match. future keys: {future}")
                if future:
                    fv_exp = min(future.values())
                    print(f"Using nearest future expiry: {fv_exp}")
                elif meta:
                    fv_exp = max(v.get("expiration_time", 0) for v in meta.values())
                    print(f"Using max expiry: {fv_exp}")
        if os.path.exists("historical_data/cmx/regression.json"):
            with open("historical_data/cmx/regression.json", "r") as f:
                d = json.load(f)
                fv_m, fv_c = d.get("slope"), d.get("intercept")
                print(f"Regression: slope={fv_m}, intercept={fv_c}")
    except Exception as e:
        print(f"ERROR: {e}")

print(f"\nResult: fv_m={fv_m}, fv_c={fv_c}, fv_exp={fv_exp}")
if fv_m and fv_c and fv_exp:
    dte = (fv_exp - time.time()) / 86400.0
    fv = round(fv_m * dte + fv_c, 2)
    print(f"Current FV (DTE={dte:.1f}): {fv}")
else:
    print("FV cannot be computed - missing m, c, or exp!")
