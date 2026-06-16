import pandas as pd
import os

def load_and_rename(filepath, prefix):
    if not os.path.exists(filepath):
        return pd.DataFrame()
    df = pd.read_csv(filepath)
    df['time'] = pd.to_datetime(df['time'])
    
    # Calculate mid price if not exists
    if 'mid' not in df.columns:
        if 'bid' in df.columns and 'offer' in df.columns:
            df['price'] = (df['bid'] + df['offer']) / 2
        elif 'close' in df.columns:
            df['price'] = df['close']
    else:
        df['price'] = df['mid']
        
    df = df[['time', 'price']].rename(columns={'price': prefix})
    return df

def main():
    cmx = load_and_rename('historical_data/CMX.MGC_Continuous_H1.csv', 'CMX.MGC')
    xau = load_and_rename('historical_data/XAUUSD.sc_H1_Vantage.csv', 'XAUUSD.sc')
    nyx = load_and_rename('historical_data/NYX.MCLE_Continuous_H1.csv', 'NYX.MCLE')
    uso = load_and_rename('historical_data/USOUSD.sc_H1_Vantage.csv', 'USOUSD.sc')
    uko = load_and_rename('historical_data/UKOUSD.sc_H1_Vantage.csv', 'UKOUSD.sc')

    dfs = [df for df in [cmx, xau, nyx, uso, uko] if not df.empty]
    
    if not dfs:
        print("No data found to merge.")
        return

    # Start with the first dataframe and outer merge the rest to keep all times
    merged_df = dfs[0]
    for df in dfs[1:]:
        merged_df = pd.merge(merged_df, df, on='time', how='outer')
        
    merged_df = merged_df.sort_values('time').reset_index(drop=True)
    
    output_path = 'historical_data/All_Symbols_H1_Merged.csv'
    merged_df.to_csv(output_path, index=False)
    print(f"Successfully merged all symbols into {output_path}")

if __name__ == '__main__':
    main()
