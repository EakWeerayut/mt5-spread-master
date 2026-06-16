import urllib.request
import json

url = "http://localhost:8080/api/history"
params = "symbol1=CMX.MGC07&symbol2=XAUUSD.sc"

try:
    req = urllib.request.urlopen(f"{url}?{params}")
    data = json.loads(req.read().decode("utf-8"))
    cd = data.get("chart_data", [])
    print(f"Status: {data.get('status')}")
    print(f"Chart data points: {len(cd)}")
    if cd:
        sample = cd[-1]
        print(f"Last point keys: {list(sample.keys())}")
        print(f"Last point: {sample}")
        has_fv = any("fair_value" in p for p in cd)
        print(f"has_fair_value: {has_fv}")
except Exception as e:
    print(f"Error: {e}")
