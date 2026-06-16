import os
from datetime import datetime
from pathlib import Path
import sys
import gspread
sys.path.insert(0, r"C:\Git\credentials")
from central_creds import get_credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


def _get_client() -> gspread.Client:
    creds = get_credentials(SCOPES)
    return gspread.authorize(creds)


def _get_or_create_worksheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        ws = spreadsheet.worksheet(title)
        ws.clear()
        return ws
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=1000, cols=30)


def _add_timestamp(ws: gspread.Worksheet, row: int):
    now = datetime.utcnow().strftime(TIMESTAMP_FORMAT)
    ws.update_cell(row, 1, f"Last Updated: {now}")


def write_sbi(spreadsheet: gspread.Spreadsheet, data: dict):
    ws = _get_or_create_worksheet(spreadsheet, "SBI")
    records = data.get("extracted_records", [])

    rows = []
    for record in records:
        name = record.get("name", "")
        total_amount = record.get("total_amount")
        line_available = record.get("line_available")
        source = record.get("source", "")
        csv_updated = record.get("csv_updated")

        if source == "ocr-review":
            source_label = "Claude/OCR ✓"
        elif source == "ocr":
            source_label = "OCR ✓"
        elif source == "cache":
            source_label = "Cache (OCR)"
        elif source == "csv":
            ts = f" (updated: {csv_updated})" if csv_updated else ""
            source_label = f"CSV{ts}"
        else:
            source_label = source or "unknown"

        rows.append([f"=== {name} ===", f"Source: {source_label}"])
        if total_amount is not None:
            rows.append(["ต้นทุนรวม", total_amount])
        if line_available is not None:
            rows.append(["Line Available", line_available])

        holdings = record.get("holdings", [])
        if holdings:
            rows.append([])
            rows.append(["HOLDINGS"])
            rows.append(["Symbol", "Side", "Amount", "Avg", "Market", "%U.PL"])
            for h in holdings:
                rows.append([h["symbol"], h.get("side", ""), h.get("amount"), h.get("avg"), h.get("market"), h.get("upnl_pct")])

        stop_orders = record.get("stop_orders", [])
        if stop_orders:
            rows.append([])
            rows.append(["STOP ORDERS"])
            rows.append(["Symbol", "Side", "Type", "Trigger Price", "Volume"])
            for o in stop_orders:
                rows.append([o["symbol"], o.get("side", ""), o.get("type", ""), o.get("trigger_price"), o.get("volume")])

        rows.append([])

    if not rows:
        rows = [["No data extracted yet."]]

    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote SBI tab: {len(records)} record(s)")


def _write_section(ws: gspread.Worksheet, current_row: int, title: str, headers: list, rows_data: list) -> int:
    ws.update_cell(current_row, 1, title)
    current_row += 1
    all_rows = [headers] + rows_data
    ws.update(all_rows, f"A{current_row}")
    current_row += len(all_rows) + 2
    return current_row


def write_binance(spreadsheet: gspread.Spreadsheet, data: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Binance")
    current_row = 1

    # SPOT BALANCES
    spot_balances = data.get("spot_balances", [])
    current_row = _write_section(
        ws, current_row, "SPOT BALANCES",
        ["Asset", "Free", "Locked", "Total"],
        [[b["asset"], b["free"], b["locked"], b["total"]] for b in spot_balances],
    )

    # EARN BALANCES
    earn_balances = data.get("earn_balances", [])
    current_row = _write_section(
        ws, current_row, "EARN BALANCES",
        ["Asset", "Product ID", "Amount", "APY", "Type"],
        [[e["asset"], e["product_id"], e["amount"], e["apy"], e["type"]] for e in earn_balances],
    )

    # FUTURES BALANCES
    futures_balances = data.get("futures_balances", [])
    current_row = _write_section(
        ws, current_row, "FUTURES BALANCES",
        ["Asset", "Wallet Balance", "Unrealized PnL", "Available Balance"],
        [[b["asset"], b["wallet_balance"], b["unrealized_pnl"], b["available_balance"]] for b in futures_balances],
    )

    # FUTURES POSITIONS
    futures_positions = data.get("futures_positions", [])
    current_row = _write_section(
        ws, current_row, "FUTURES POSITIONS",
        ["Symbol", "Side", "Amount", "Entry Price", "Mark Price", "Unrealized PnL", "Leverage", "Margin Type"],
        [[p["symbol"], p["position_side"], p["position_amt"], p["entry_price"],
          p["mark_price"], p["unrealized_pnl"], p["leverage"], p["margin_type"]]
         for p in futures_positions],
    )

    # FUTURES ORDERS
    futures_orders = data.get("futures_orders", [])
    current_row = _write_section(
        ws, current_row, "FUTURES ORDERS",
        ["Symbol", "Order ID", "Side", "Type", "Price", "Orig Qty", "Executed Qty", "Stop Price", "Status", "Time"],
        [[o["symbol"], o["order_id"], o["side"], o["type"], o["price"],
          o["orig_qty"], o["executed_qty"], o["stop_price"], o["status"], o["time"]]
         for o in futures_orders],
    )

    # SPOT ORDERS
    spot_orders = data.get("spot_orders", [])
    current_row = _write_section(
        ws, current_row, "SPOT ORDERS",
        ["Symbol", "Order ID", "Side", "Type", "Price", "Orig Qty", "Executed Qty", "Status", "Time"],
        [[o["symbol"], o["order_id"], o["side"], o["type"], o["price"],
          o["orig_qty"], o["executed_qty"], o["status"], o["time"]]
         for o in spot_orders],
    )

    _add_timestamp(ws, current_row)
    print(
        f"  [Sheets] Wrote Binance: {len(spot_balances)} spot balance(s), "
        f"{len(earn_balances)} earn position(s), {len(futures_balances)} futures balance(s), "
        f"{len(futures_positions)} futures position(s), {len(futures_orders)} futures order(s), "
        f"{len(spot_orders)} spot order(s)"
    )


def write_deribit(spreadsheet: gspread.Spreadsheet, data: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Deribit")
    current_row = 1

    # Account summaries
    ws.update_cell(current_row, 1, "ACCOUNT SUMMARY")
    current_row += 1
    summaries = data.get("account_summaries", [])
    sum_headers = ["Currency", "Equity", "Balance", "Available Funds", "Margin Balance", "Unrealized PnL", "Initial Margin"]
    sum_rows = [sum_headers] + [
        [s["currency"], s["equity"], s["balance"], s["available_funds"],
         s["margin_balance"], s["unrealized_pnl"], s["initial_margin"]]
        for s in summaries
    ]
    ws.update(sum_rows, f"A{current_row}")
    current_row += len(sum_rows) + 2

    # Open positions
    ws.update_cell(current_row, 1, "OPEN POSITIONS")
    current_row += 1
    positions = data.get("open_positions", [])
    pos_headers = ["Instrument", "Size", "Direction", "Avg Price", "Mark Price", "Index Price",
                   "Floating PnL", "Realized PnL", "Delta", "Currency"]
    pos_rows = [pos_headers] + [
        [p["instrument"], p["size"], p["direction"], p["average_price"], p["mark_price"],
         p["index_price"], p["floating_pnl"], p["realized_pnl"], p["delta"], p["currency"]]
        for p in positions
    ]
    ws.update(pos_rows, f"A{current_row}")
    current_row += len(pos_rows) + 2

    # Open orders
    ws.update_cell(current_row, 1, "OPEN ORDERS")
    current_row += 1
    orders = data.get("open_orders", [])
    ord_headers = ["Order ID", "Instrument", "Direction", "Type", "Price", "Amount", "Filled", "Status", "Currency"]
    ord_rows = [ord_headers] + [
        [o["order_id"], o["instrument"], o["direction"], o["order_type"],
         o["price"], o["amount"], o["filled_amount"], o["status"], o["currency"]]
        for o in orders
    ]
    ws.update(ord_rows, f"A{current_row}")
    current_row += len(ord_rows) + 2

    _add_timestamp(ws, current_row)
    print(f"  [Sheets] Wrote Deribit: {len(summaries)} currency summary(ies), {len(positions)} position(s), {len(orders)} order(s)")


def write_deribit_log(spreadsheet: gspread.Spreadsheet, data: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Deribit Log")
    
    logs = data.get("transaction_logs", [])
    if not logs:
        ws.update_cell(1, 1, "No transaction logs found.")
        _add_timestamp(ws, 3)
        return

    headers = ["Log ID", "Time (UTC)", "Type", "Currency", "Instrument", "Amount", "Balance", "Fee", "Side", "Info"]
    rows = [headers]
    
    # Sort logs by timestamp descending
    sorted_logs = sorted(logs, key=lambda x: x.get("timestamp", 0), reverse=True)
    
    for log in sorted_logs:
        ts = log.get("timestamp")
        time_str = datetime.utcfromtimestamp(ts / 1000).strftime(TIMESTAMP_FORMAT) if ts else ""
        
        # Determine amount - could be 'amount' or 'change' depending on type
        amount = log.get("amount") if "amount" in log else log.get("change")
        
        info_val = log.get("info", "")
        if isinstance(info_val, dict) or isinstance(info_val, list):
            import json
            info_val = json.dumps(info_val)
            
        rows.append([
            log.get("id"),
            time_str,
            log.get("type"),
            log.get("_currency") or log.get("currency"),
            log.get("instrument_name", ""),
            amount,
            log.get("balance"),
            log.get("fee"),
            log.get("side", ""),
            info_val
        ])

    try:
        if ws.row_count < len(rows) + 5:
            ws.add_rows(len(rows) + 5 - ws.row_count)
    except Exception:
        pass

    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote Deribit Log: {len(logs)} entry(ies)")



def _write_mt5_account(spreadsheet: gspread.Spreadsheet, account: dict):
    label = account.get("label", "?")
    tab_name = f"MT5 ({label})"
    ws = _get_or_create_worksheet(spreadsheet, tab_name)
    current_row = 1

    # Account info
    ws.update_cell(current_row, 1, "ACCOUNT INFO")
    current_row += 1
    info = account.get("account_info", {})
    info_rows = [[k.replace("_", " ").title(), v] for k, v in info.items()]
    ws.update(info_rows, f"A{current_row}")
    current_row += len(info_rows) + 2

    # Open positions
    ws.update_cell(current_row, 1, "OPEN POSITIONS")
    current_row += 1
    positions = account.get("open_positions", [])
    pos_headers = ["Ticket", "Symbol", "Type", "Volume", "Open Price", "Current Price", "SL", "TP", "Profit", "Swap", "Comment"]
    pos_rows = [pos_headers] + [
        [p["ticket"], p["symbol"], p["type"], p["volume"], p["open_price"],
         p["current_price"], p["sl"], p["tp"], p["profit"], p["swap"], p["comment"]]
        for p in positions
    ]
    ws.update(pos_rows, f"A{current_row}")
    current_row += len(pos_rows) + 2

    # Open orders
    ws.update_cell(current_row, 1, "OPEN ORDERS")
    current_row += 1
    orders = account.get("open_orders", [])
    ord_headers = ["Ticket", "Symbol", "Type", "Volume", "Price", "SL", "TP", "Comment"]
    ord_rows = [ord_headers] + [
        [o["ticket"], o["symbol"], o["type"], o["volume"],
         o["price"], o["sl"], o["tp"], o["comment"]]
        for o in orders
    ]
    ws.update(ord_rows, f"A{current_row}")
    current_row += len(ord_rows) + 2

    _add_timestamp(ws, current_row)
    print(f"  [Sheets] Wrote {tab_name}: {len(positions)} position(s), {len(orders)} order(s)")


def write_mt5(spreadsheet: gspread.Spreadsheet, data: dict):
    for account in data.get("accounts", []):
        _write_mt5_account(spreadsheet, account)


def write_order(spreadsheet: gspread.Spreadsheet, results: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Order")

    rows = [["Sheet", "Type", "Symbol", "Side", "Order Type", "Price", "Orig Qty", "Executed Qty", "Stop Price"]]

    if "binance" in results:
        for o in results["binance"].get("futures_orders", []):
            rows.append([
                "Binance", "FUTURES ORDERS",
                f"{o['symbol']}.P", o["side"], o["type"],
                o["price"], o["orig_qty"], o["executed_qty"], o["stop_price"],
            ])
        for o in results["binance"].get("spot_orders", []):
            rows.append([
                "Binance", "SPOT ORDERS",
                o["symbol"], o["side"], o["type"],
                o["price"], o["orig_qty"], o["executed_qty"], "",
            ])

    if "deribit" in results:
        for o in results["deribit"].get("open_orders", []):
            rows.append([
                "Deribit", "OPEN ORDERS",
                o["instrument"], o["direction"], o["order_type"],
                o["price"], o["amount"], o["filled_amount"], "",
            ])

    if "sbi" in results:
        for record in results["sbi"].get("extracted_records", []):
            for o in record.get("stop_orders", []):
                rows.append([
                    "SBI", "STOP ORDERS",
                    o["symbol"], o["side"], o["type"],
                    o["trigger_price"], o["volume"], "", "",
                ])

    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote Order tab: {len(rows) - 1} row(s)")


def write_position(spreadsheet: gspread.Spreadsheet, results: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Position")

    rows = [["Sheet", "Type", "Symbol", "Side", "Amount", "Entry Price", "Mark Price", "Swap"]]

    if "binance" in results:
        for p in results["binance"].get("futures_positions", []):
            rows.append([
                "Binance", "FUTURES POSITIONS",
                f"{p['symbol']}.P", p["position_side"], p["position_amt"],
                p["entry_price"], p["mark_price"], "",
            ])

    if "deribit" in results:
        for p in results["deribit"].get("open_positions", []):
            rows.append([
                "Deribit", "OPEN POSITIONS",
                p["instrument"], p["direction"], p["size"],
                p["average_price"], p["mark_price"], "",
            ])

    if "mt5" in results:
        from collections import defaultdict
        groups = defaultdict(list)
        for account in results["mt5"].get("accounts", []):
            for p in account.get("open_positions", []):
                groups[(p["symbol"], p["type"])].append(p)

        for (symbol, side), positions in sorted(groups.items()):
            total_volume = sum(p["volume"] for p in positions)
            avg_entry = (
                sum(p["volume"] * p["open_price"] for p in positions) / total_volume
                if total_volume else 0
            )
            mark_price = positions[0]["current_price"]
            total_swap = sum(p.get("swap") or 0 for p in positions)
            rows.append([
                "MT5", "OPEN POSITIONS",
                symbol, side, total_volume,
                avg_entry, mark_price, total_swap,
            ])

    if "sbi" in results:
        for record in results["sbi"].get("extracted_records", []):
            for h in record.get("holdings", []):
                rows.append([
                    "SBI", "HOLDINGS",
                    h["symbol"], h.get("side", ""), h.get("amount"),
                    h["avg"], h["market"], "",
                ])

    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote Position tab: {len(rows) - 1} row(s)")


def write_asset(spreadsheet: gspread.Spreadsheet, results: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Asset")

    rows = [["Sheet", "Type", "Asset", "Amount"]]

    if "binance" in results:
        for b in results["binance"].get("spot_balances", []):
            rows.append(["Binance", "SPOT BALANCES", b["asset"], b["free"]])
        for e in results["binance"].get("earn_balances", []):
            rows.append(["Binance", "EARN BALANCES", e["asset"], e["amount"]])
        for f in results["binance"].get("futures_balances", []):
            rows.append(["Binance", "FUTURES BALANCES", f["asset"], f["wallet_balance"]])

    if "deribit" in results:
        for s in results["deribit"].get("account_summaries", []):
            rows.append(["Deribit", "ACCOUNT SUMMARY", s["currency"], s["balance"]])

    if "mt5" in results:
        for account in results["mt5"].get("accounts", []):
            label = account.get("label", "?")
            info = account.get("account_info", {})
            rows.append([f"MT5 ({label})", "ACCOUNT INFO", "", info.get("balance")])

    if "sbi" in results:
        for record in results["sbi"].get("extracted_records", []):
            if record.get("total_amount") is not None:
                rows.append(["SBI", "SUMMARY", "", record["total_amount"]])
            if record.get("image_type") == "stocks" and record.get("line_available") is not None:
                rows.append(["SBI", "SUMMARY", "", record["line_available"]])

    if "lib" in results:
        balance = results["lib"].get("ending_cash_balance")
        if balance is not None:
            rows.append(["LIB", "Ending Balance", "", balance])

    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote Asset tab: {len(rows) - 1} row(s)")


def write_summary(spreadsheet: gspread.Spreadsheet, results: dict, usd_thb_rate: float = 35.0):
    ws = _get_or_create_worksheet(spreadsheet, "Summary")

    rows = [
        ["Platform Summary"],
        [],
        ["Platform", "Metric", "Value (USD)", "Value (THB)"],
    ]

    # SBI — images downloaded; extraction handled externally by Claude Code agent
    if "sbi" in results:
        n = len(results["sbi"].get("image_paths", []))
        rows.append(["SBI", f"{n} image(s) downloaded — extraction by Claude Code agent", "N/A", "N/A"])

    # Binance — sum spot balances total (non-stable values would need price lookup; show raw totals)
    if "binance" in results:
        futures = results["binance"].get("futures_positions", [])
        unrealized = sum(f.get("unrealized_pnl") or 0 for f in futures)
        rows.append(["Binance", "Futures Unrealized PnL (USD)", unrealized, unrealized * usd_thb_rate])

    # Deribit — sum equity across currencies in USD equivalent (BTC/ETH would need price; show raw)
    if "deribit" in results:
        summaries = results["deribit"].get("account_summaries", [])
        for s in summaries:
            equity = s.get("equity") or 0
            currency = s.get("currency", "")
            rows.append([f"Deribit ({currency})", "Equity", equity, "N/A (non-USD)"])

    # MT5 — balance + equity per account
    if "mt5" in results:
        for account in results["mt5"].get("accounts", []):
            label = account.get("label", "?")
            info = account.get("account_info", {})
            currency = info.get("currency", "")
            equity = info.get("equity") or 0
            balance = info.get("balance") or 0
            thb_balance = balance * usd_thb_rate if currency == "USD" else "N/A"
            thb_equity = equity * usd_thb_rate if currency == "USD" else "N/A"
            rows.append([f"MT5 Account {label} ({currency})", "Balance", balance, thb_balance])
            rows.append([f"MT5 Account {label} ({currency})", "Equity", equity, thb_equity])

    rows.append([])
    rows.append(["Note", f"THB conversion rate used: {usd_thb_rate} THB/USD"])

    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print("  [Sheets] Wrote Summary tab")


def write_binance_market(spreadsheet: gspread.Spreadsheet, data: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Binance Market")
    rows = [["Symbol", "Price (USDT)", "Avg Volume (USD/day)"]]
    for r in data.get("rows", []):
        rows.append([r["symbol"], r["price"], r["avg_volume_usd"]])
    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote Binance Market tab: {len(rows) - 1} symbol(s)")


def write_set_market(spreadsheet: gspread.Spreadsheet, data: dict):
    ws = _get_or_create_worksheet(spreadsheet, "SET Market")
    rows = [["Symbol", "Price (THB)", "Avg Volume (THB/day)"]]
    for r in data.get("rows", []):
        rows.append([r["symbol"], r["price"], r["avg_volume_thb"]])
    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote SET Market tab: {len(rows) - 1} symbol(s)")


def write_market_options(spreadsheet: gspread.Spreadsheet, data: dict):
    ws = _get_or_create_worksheet(spreadsheet, "Options Market")
    rows = [["Exchange", "Symbol", "Underlying", "Expiry Date", "Strike", "Type", "Bid", "Ask", "Mark Price", "Volume", "Open Interest", "IV"]]
    for r in data.get("rows", []):
        rows.append([
            r["exchange"], r["symbol"], r["underlying"], r["expiry_date"],
            r["strike"], r["type"], r["bid"], r["ask"], r["mark_price"],
            r["volume"], r["open_interest"], r["iv"]
        ])
        
    try:
        if ws.row_count < len(rows) + 5:
            ws.add_rows(len(rows) + 5 - ws.row_count)
    except Exception as e:
        pass # add_rows might fail or not be supported in older versions, ignore
        
    ws.update(rows, "A1")
    _add_timestamp(ws, len(rows) + 2)
    print(f"  [Sheets] Wrote Options Market tab: {len(rows) - 1} option(s)")


def write_all(results: dict):
    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "Portfolio Tracker").strip()
    print(f"  [Sheets] Opening spreadsheet: {sheet_name}")

    if "sbi" in results:
        import re
        for record in results["sbi"].get("extracted_records", []):
            is_futures = record.get("image_type") == "futures"
            for h in record.get("holdings", []):
                if h.get("symbol"):
                    # Remove anything in parentheses and then any stray parenthesis characters
                    sym_clean = re.sub(r'\s*\([^)]*\)', '', h["symbol"])
                    sym_clean = re.sub(r'[\(\)（）]', '', sym_clean).strip()
                    h["symbol"] = sym_clean

                if is_futures and h.get("amount") is not None:
                    sym = h.get("symbol", "").upper()
                    multiplier = 200 if sym.startswith("S50") else 1000
                    h["amount"] = h["amount"] * multiplier
                    
                if h.get("amount") is not None:
                    side = h.get("side", "").upper()
                    if "SHORT" in side or "SELL" in side:
                        h["amount"] = -abs(h["amount"])
                    
            for o in record.get("stop_orders", []):
                if o.get("symbol"):
                    sym_clean = re.sub(r'\s*\([^)]*\)', '', o["symbol"])
                    sym_clean = re.sub(r'[\(\)（）]', '', sym_clean).strip()
                    o["symbol"] = sym_clean

                if o.get("volume") is not None:
                    sym = o.get("symbol", "").upper()
                    # Check if TFEX symbol (S50... or ends with month code + 2 digits e.g., M24)
                    is_tfex = sym.startswith("S50") or bool(re.search(r'[FGHJKMNQUVXZ]\d{2}$', sym))
                    if is_tfex:
                        multiplier = 200 if sym.startswith("S50") else 1000
                        o["volume"] = o["volume"] * multiplier

    gc = _get_client()
    try:
        spreadsheet = gc.open(sheet_name)
    except gspread.SpreadsheetNotFound:
        print(f"  [Sheets] Spreadsheet not found, creating: {sheet_name}")
        spreadsheet = gc.create(sheet_name)

    if "sbi" in results:
        write_sbi(spreadsheet, results["sbi"])

    if "binance" in results:
        write_binance(spreadsheet, results["binance"])

    if "deribit" in results:
        write_deribit(spreadsheet, results["deribit"])

    if "mt5" in results:
        write_mt5(spreadsheet, results["mt5"])

    write_order(spreadsheet, results)
    write_position(spreadsheet, results)
    write_asset(spreadsheet, results)
    write_summary(spreadsheet, results)

    if "market_binance" in results:
        write_binance_market(spreadsheet, results["market_binance"])

    if "market_options" in results:
        write_market_options(spreadsheet, results["market_options"])

    print(f"  [Sheets] Done. Spreadsheet URL: {spreadsheet.url}")
    return spreadsheet.url
