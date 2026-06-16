import pandas as pd
import matplotlib.pyplot as plt
import os

def load_data(file_path):
    if not os.path.exists(file_path):
        return pd.DataFrame()
    df = pd.read_csv(file_path)
    df['time'] = pd.to_datetime(df['time'])
    return df.set_index('time')

def main():
    gold = load_data('historical_data/Gold_H1_Final.csv')
    oil = load_data('historical_data/Oil_H1_Final_v3.csv')

    plt.style.use('dark_background')
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 12))

    # 1. Gold Spread
    if not gold.empty:
        ax1.plot(gold.index, gold['spread'], label='Gold Spread (Futures - Spot)', color='#ffd700', linewidth=1.5)
        ax1.axhline(0, color='white', linestyle='--', alpha=0.5)
        ax1.set_title('Gold Spread: CMX.MGC Futures - XAUUSD Spot (H1)', fontsize=14, color='#ffd700')
        ax1.set_ylabel('Spread ($)', fontsize=12)
        ax1.legend()
        ax1.grid(True, alpha=0.2)

    # 2. WTI Spread
    if not oil.empty:
        ax2.plot(oil.index, oil['spread'], label='WTI Spread (Spot - Futures)', color='#1f77b4', linewidth=1.5)
        ax2.axhline(0, color='white', linestyle='--', alpha=0.5)
        ax2.set_title('WTI Oil Spread: USOUSD Spot - NYX.MCLE Futures (H1)', fontsize=14, color='#1f77b4')
        ax2.set_ylabel('Spread ($)', fontsize=12)
        ax2.legend()
        ax2.grid(True, alpha=0.2)

        # 3. Brent-WTI Spread
        ax3.plot(oil.index, oil['spread_UK_US'], label='Brent - WTI Spread (Spot)', color='#2ca02c', linewidth=1.5)
        ax3.axhline(0, color='white', linestyle='--', alpha=0.5)
        ax3.set_title('Brent-WTI Spread: UKOUSD Brent - USOUSD WTI Spot (H1)', fontsize=14, color='#2ca02c')
        ax3.set_ylabel('Spread ($)', fontsize=12)
        ax3.legend()
        ax3.grid(True, alpha=0.2)

    plt.tight_layout()
    import sys
    if len(sys.argv) > 1:
        output_path = sys.argv[1]
    else:
        output_path = 'historical_data/charts.png'
        
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150)
    print(f"Saved chart to {output_path}")

if __name__ == '__main__':
    main()
