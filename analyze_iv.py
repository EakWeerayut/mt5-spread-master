import json
from collections import defaultdict

def main():
    try:
        with open("option/deribit_options.json", "r") as f:
            deribit_data = json.load(f)
    except Exception as e:
        print("Error loading json:", e)
        return

    btc_options = []
    btc_price = 0

    for item in deribit_data:
        inst = item.get("instrument_name", "")
        parts = inst.split("-")
        if len(parts) == 4 and parts[0] == "BTC":
            iv = item.get("mark_iv")
            if iv is None or iv <= 0:
                continue
            
            underlying = item.get("underlying_price", 0)
            if underlying > 0:
                btc_price = underlying
                
            bid_val = item.get("bid_price")
            ask_val = item.get("ask_price")
            mark_val = item.get("mark_price")
            btc_options.append({
                "instrument": inst,
                "expiry": parts[1],
                "strike": float(parts[2]),
                "type": parts[3],
                "iv": iv,
                "bid": (bid_val if bid_val is not None else 0) * underlying,
                "ask": (ask_val if ask_val is not None else 0) * underlying,
                "mark": (mark_val if mark_val is not None else 0) * underlying
            })

    if not btc_options:
        print("No BTC options found.")
        return

    print(f"Current BTC Price (approx): ${btc_price:,.2f}")
    
    # Analyze by Expiry
    expiry_groups = defaultdict(list)
    for opt in btc_options:
        expiry_groups[opt["expiry"]].append(opt)

    print("\n--- IV Analysis (Cheap to Buy vs Expensive to Sell) ---")
    
    # Find overall cheapest (lowest IV) and most expensive (highest IV)
    # Filter for options with some liquidity (bid > 0 and ask > 0)
    liquid_options = [o for o in btc_options if o["bid"] > 0 and o["ask"] > 0]
    
    if not liquid_options:
        print("No liquid options found.")
        liquid_options = btc_options # Fallback to all if none are perfectly liquid
        
    liquid_options.sort(key=lambda x: x["iv"])
    
    print("\nTop 5 CHEAPEST Options (Lowest IV - Good for LONG strategy):")
    for opt in liquid_options[:5]:
        moneyness = "OTM" if (opt["type"]=="C" and opt["strike"]>btc_price) or (opt["type"]=="P" and opt["strike"]<btc_price) else "ITM"
        print(f"{opt['instrument']} (Strike: ${opt['strike']:,.0f}, {moneyness}) -> IV: {opt['iv']:.2f}% | Ask: ${opt['ask']:.2f}")

    print("\nTop 5 MOST EXPENSIVE Options (Highest IV - Good for SHORT strategy):")
    for opt in liquid_options[-5:]:
        moneyness = "OTM" if (opt["type"]=="C" and opt["strike"]>btc_price) or (opt["type"]=="P" and opt["strike"]<btc_price) else "ITM"
        print(f"{opt['instrument']} (Strike: ${opt['strike']:,.0f}, {moneyness}) -> IV: {opt['iv']:.2f}% | Bid: ${opt['bid']:.2f}")

    # Let's also look specifically at OTM Puts (for hedging) and OTM Calls (for yield)
    otm_puts = [o for o in liquid_options if o["type"] == "P" and o["strike"] < btc_price * 0.95]
    otm_calls = [o for o in liquid_options if o["type"] == "C" and o["strike"] > btc_price * 1.05]
    
    otm_puts.sort(key=lambda x: x["iv"])
    otm_calls.sort(key=lambda x: x["iv"], reverse=True)
    
    print("\nTop 3 CHEAPEST OTM Puts (Best value for Downside Protection / Long Put):")
    for opt in otm_puts[:3]:
        print(f"{opt['instrument']} -> IV: {opt['iv']:.2f}% | Ask: ${opt['ask']:.2f} (Strike: ${opt['strike']:,.0f})")
        
    print("\nTop 3 MOST EXPENSIVE OTM Calls (Best value for Yield Generation / Short Call):")
    for opt in otm_calls[:3]:
        print(f"{opt['instrument']} -> IV: {opt['iv']:.2f}% | Bid: ${opt['bid']:.2f} (Strike: ${opt['strike']:,.0f})")

if __name__ == '__main__':
    main()
