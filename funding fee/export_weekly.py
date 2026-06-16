import pandas as pd

def export_weekly():
    print("Loading daily summary...")
    df = pd.read_csv("daily_funding_summary.csv")
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    
    # Resample to Weekly (W = Sunday end of week)
    # Average the annualized APY over the week
    # For BTC price, we can use the average price of the week or the last price. 
    # Let's take the mean for all columns to represent the week's average level.
    df_weekly = df.resample('W').mean()
    
    # Round everything nicely
    df_weekly = df_weekly.round(2)
    
    df_weekly.index.name = 'Week_Starting'
    df_weekly.reset_index(inplace=True)
    
    # Adjust index to show the start of the week (Monday) instead of end (Sunday) for clarity
    df_weekly['Week_Starting'] = df_weekly['Week_Starting'] - pd.Timedelta(days=6)
    df_weekly['Week_Starting'] = df_weekly['Week_Starting'].dt.date
    
    # Drop rows that are completely NaN in APY
    df_weekly.dropna(subset=['Binance_USDT_APY_%', 'Deribit_BTC_APY_%'], how='all', inplace=True)
    
    out_file = "weekly_funding_summary.csv"
    df_weekly.to_csv(out_file, index=False)
    print(f"Exported {len(df_weekly)} weeks of data to {out_file}")

if __name__ == "__main__":
    export_weekly()
