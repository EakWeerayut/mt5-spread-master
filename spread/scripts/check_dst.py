import pandas as pd

def analyze_open_times():
    cmx = pd.read_csv('historical_data/CMX.MGC_Continuous_H1.csv')
    cmx['time'] = pd.to_datetime(cmx['time'])
    
    xau = pd.read_csv('historical_data/XAUUSD.sc_H1_Vantage.csv')
    xau['time'] = pd.to_datetime(xau['time'])
    
    # Let's pick a date in January 2026 (Winter)
    # Sunday is dayofweek=6, Monday is 0.
    cmx_jan = cmx[(cmx['time'].dt.month == 1) & (cmx['time'].dt.year == 2026)]
    xau_jan = xau[(xau['time'].dt.month == 1) & (xau['time'].dt.year == 2026)]
    
    print("MTS (CMX) First tick on a Monday in Jan 2026 (Winter):")
    print(cmx_jan[cmx_jan['time'].dt.dayofweek == 0]['time'].min())
    
    print("Vantage (XAU) First tick on a Monday in Jan 2026 (Winter):")
    print(xau_jan[xau_jan['time'].dt.dayofweek == 0]['time'].min())
    
    # Pick a date in April 2026 (Summer DST)
    cmx_apr = cmx[(cmx['time'].dt.month == 4) & (cmx['time'].dt.year == 2026)]
    xau_apr = xau[(xau['time'].dt.month == 4) & (xau['time'].dt.year == 2026)]
    
    print("\nMTS (CMX) First tick on a Monday in Apr 2026 (Summer):")
    print(cmx_apr[cmx_apr['time'].dt.dayofweek == 0]['time'].min())
    
    print("Vantage (XAU) First tick on a Monday in Apr 2026 (Summer):")
    print(xau_apr[xau_apr['time'].dt.dayofweek == 0]['time'].min())

if __name__ == "__main__":
    analyze_open_times()
