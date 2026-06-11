# MT5 Spread Master

A multi-broker spread trading and analysis system for MetaTrader 5. 
This system connects to multiple MT5 terminals to fetch live prices, historical data, and execute cross-broker spread trades for instruments like Oil (USO/UKO), Gold (CMX), and Indices.

## Features
- **Live Spread Monitoring**: Track real-time bid/ask spreads across two different MT5 brokers.
- **Fair Value Analysis**: Regression-based analysis and historical data charting to find optimal entry points.
- **Automated Spread Trading**: Place limit orders based on target spread thresholds.
- **Market Sessions**: View market hours to ensure safe trading windows.

## Setup
1. Clone this repository.
2. Ensure you have Python 3.9+ and install requirements (if any, e.g. `pip install matplotlib pandas MetaTrader5`).
3. Copy `.env.example` to `.env` and fill in your MT5 account credentials.
4. Update `spread_trader_config.json` with your preferred terminal paths.
5. Run the server: `python server.py`
6. Open `http://localhost:8080` in your web browser.

## Security Note
This repository contains no personal account information. All sensitive credentials are excluded via `.gitignore`.
