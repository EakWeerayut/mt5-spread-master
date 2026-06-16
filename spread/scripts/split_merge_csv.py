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

def merge_group(name, file_configs):
    dfs = []
    for filepath, prefix in file_configs:
        df = load_and_rename(filepath, prefix)
        if not df.empty:
            dfs.append(df)
            
    if not dfs:
        print(f"No data found for {name}.")
        return

    # Use 'inner' join so that timestamps without complete data across all symbols are dropped
    merged_df = dfs[0]
    for df in dfs[1:]:
        merged_df = pd.merge(merged_df, df, on='time', how='inner')
        
    merged_df = merged_df.sort_values('time').reset_index(drop=True)
    
    output_path = f'historical_data/{name}_H1_Merged_Complete.csv'
    merged_df.to_csv(output_path, index=False)
    print(f"Successfully merged {name}! Total valid rows (complete data): {len(merged_df)}")
    print(f"Saved to {output_path}")

def main():
    gold_files = [
        ('historical_data/CMX.MGC_Continuous_H1.csv', 'CMX.MGC'),
        ('historical_data/XAUUSD.sc_H1_Vantage.csv', 'XAUUSD.sc')
    ]
    
    oil_files = [
        ('historical_data/NYX.MCLE_Continuous_H1.csv', 'NYX.MCLE'),
        ('historical_data/USOUSD.sc_H1_Vantage.csv', 'USOUSD.sc'),
        ('historical_data/UKOUSD.sc_H1_Vantage.csv', 'UKOUSD.sc')
    ]

    print("--- Processing Gold ---")
    merge_group('Gold', gold_files)
    
    print("\n--- Processing Oil ---")
    merge_group('Oil', oil_files)

if __name__ == '__main__':
    main()
