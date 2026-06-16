import urllib.request
import json

# Test the /api/history endpoint
url = "http://localhost:8080/api/history"
params = "symbol1=CMX.MGCG7&symbol2=XAUUSD.sc"
full_url = f"{url}?{params}"

try:
    res = json.loads(urllib.request.urlopen(full_url).read().decode('utf-8'))
    cd = res.get("chart_data", [])
    print(f"Total chart points: {len(cd)}")
    if cd:
        print("Last point:", cd[-1])
        print("Has fair_value:", any("fair_value" in p for p in cd))
except Exception as e:
    print("Error:", e)
