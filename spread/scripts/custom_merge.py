import pandas as pd
import os

def load_data(filepath, symbol_group, contract_name, shift_hours=0):
    if not os.path.exists(filepath):
        return pd.DataFrame()
    df = pd.read_csv(filepath)
    df['time'] = pd.to_datetime(df['time'])
    
    if shift_hours != 0:
        df['time'] = df['time'] - pd.Timedelta(hours=shift_hours)
    
    if 'mid' not in df.columns:
        if 'bid' in df.columns and 'offer' in df.columns:
            df['price'] = (df['bid'] + df['offer']) / 2
        elif 'close' in df.columns:
            df['price'] = df['close']
    else:
        df['price'] = df['mid']
        
    df = df[['time', 'price']].rename(columns={'price': symbol_group})
    df[f'{symbol_group}_contract'] = contract_name
    return df

def build_continuous(prefix, schedule):
    dfs = []
    for contract, start_date, end_date in schedule:
        filepath = f'historical_data/{contract}_H1_MTS.csv'
        df = load_data(filepath, prefix, contract)
        if df.empty:
            continue
            
        if start_date:
            df = df[df['time'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['time'] < pd.to_datetime(end_date)]
            
        dfs.append(df)
        
    if not dfs:
        return pd.DataFrame()
        
    continuous = pd.concat(dfs).sort_values('time').reset_index(drop=True)
    return continuous

def main():
    print("--- 1. Building Custom Continuous Contracts (Rule-based) ---")
    
    cmx_schedule = [
        ('CMX.MGCM6', None, '2026-03-01'),
        ('CMX.MGCQ6', '2026-03-01', '2026-05-01'),
        ('CMX.MGCZ6', '2026-05-01', '2026-07-01'),
        ('CMX.MGCG7', '2026-07-01', None)
    ]
    cmx_continuous = build_continuous('CMX.MGC', cmx_schedule)
    if not cmx_continuous.empty:
        cmx_continuous.to_csv('historical_data/CMX.MGC_Continuous_H1.csv', index=False)

    nyx_schedule = [
        ('NYX.MCLEN6', None, '2026-05-01'),
        ('NYX.MCLEQ6', '2026-05-01', '2026-07-01'),
        ('NYX.MCLEU6', '2026-07-01', '2026-09-01'),
        ('NYX.MCLEV6', '2026-09-01', None)
    ]
    nyx_continuous = build_continuous('NYX.MCLE', nyx_schedule)
    if not nyx_continuous.empty:
        nyx_continuous.to_csv('historical_data/NYX.MCLE_Continuous_H1.csv', index=False)

    print("\n--- 2. Re-merging with Spot Markets (Time Aligned) ---")
    
    xau = load_data('historical_data/XAUUSD.sc_H1_Vantage.csv', 'XAUUSD.sc', None, shift_hours=3)
    uso = load_data('historical_data/USOUSD.sc_H1_Vantage.csv', 'USOUSD.sc', None, shift_hours=3)
    uko = load_data('historical_data/UKOUSD.sc_H1_Vantage.csv', 'UKOUSD.sc', None, shift_hours=3)
    
    # Merge Gold
    if not cmx_continuous.empty and not xau.empty:
        gold_merged = pd.merge(cmx_continuous, xau, on='time', how='inner')
        
        # Calculate spread and format columns
        gold_merged['spread'] = gold_merged['CMX.MGC'] - gold_merged['XAUUSD.sc']
        gold_merged = gold_merged.rename(columns={
            'CMX.MGC_contract': 'contract',
            'CMX.MGC': 'price_futures',
            'XAUUSD.sc': 'price_spot'
        })
        gold_merged = gold_merged[['time', 'spread', 'contract', 'price_futures', 'price_spot']]
        
        gold_merged = gold_merged.sort_values('time').reset_index(drop=True)
        gold_merged.to_csv('historical_data/Gold_H1_Final.csv', index=False)
        print(f"Gold Merged and Aligned. Rows: {len(gold_merged)}")
        
    # Merge Oil
    if not nyx_continuous.empty and not uso.empty and not uko.empty:
        oil_merged = pd.merge(nyx_continuous, uso, on='time', how='inner')
        oil_merged = pd.merge(oil_merged, uko, on='time', how='inner')
        
        # Calculate spread and format columns
        oil_merged['spread'] = oil_merged['USOUSD.sc'] - oil_merged['NYX.MCLE']
        oil_merged['spread_UK_US'] = oil_merged['UKOUSD.sc'] - oil_merged['USOUSD.sc']
        oil_merged = oil_merged.rename(columns={
            'NYX.MCLE_contract': 'contract',
            'NYX.MCLE': 'price_futures',
            'USOUSD.sc': 'price_wti_spot',
            'UKOUSD.sc': 'price_brent_spot'
        })
        oil_merged = oil_merged[['time', 'spread', 'spread_UK_US', 'contract', 'price_futures', 'price_wti_spot', 'price_brent_spot']]
        
        oil_merged = oil_merged.sort_values('time').reset_index(drop=True)
        oil_merged.to_csv('historical_data/Oil_H1_Final_v3.csv', index=False)
        print(f"Oil Merged and Aligned. Rows: {len(oil_merged)}")

if __name__ == '__main__':
    main()
