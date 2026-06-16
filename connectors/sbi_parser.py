"""
SBI screenshot parser using EasyOCR + bounding-box row grouping.
Supports 3 image types: stocks, futures, stop_orders.
"""

import re


# ---------------------------------------------------------------------------
# OCR + row grouping
# ---------------------------------------------------------------------------

def run_ocr(image_path: str) -> list:
    import easyocr
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    # Lower min_size and thresholds to prevent dropping single-character symbols like 'M'
    return reader.readtext(str(image_path), min_size=5, text_threshold=0.3, low_text=0.3)


def group_rows(ocr_results: list, y_tolerance: int = 15) -> list:
    """Group OCR tokens into rows using bounding-box y-coordinates."""
    rows = []
    for (bbox, text, conf) in ocr_results:
        cy = (bbox[0][1] + bbox[2][1]) / 2
        cx = bbox[0][0]
        placed = False
        for row in rows:
            if abs(row["y"] - cy) < y_tolerance:
                row["cells"].append({"x": cx, "text": text.strip(), "conf": conf})
                placed = True
                break
        if not placed:
            rows.append({"y": cy, "cells": [{"x": cx, "text": text.strip(), "conf": conf}]})
    rows.sort(key=lambda r: r["y"])
    for row in rows:
        row["cells"].sort(key=lambda c: c["x"])
    return rows


def _texts(row: dict) -> list[str]:
    return [c["text"] for c in row["cells"]]


def _all_tokens(rows: list) -> list[str]:
    return [c["text"] for row in rows for c in row["cells"]]


# ---------------------------------------------------------------------------
# Number utilities
# ---------------------------------------------------------------------------

def _parse_float(s: str):
    if not s:
        return None
    cleaned = str(s).replace(",", "").replace("~", "-").lstrip("+")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_numeric(s: str) -> bool:
    return _parse_float(s) is not None


def _find_value_after_keyword(rows: list, keyword: str):
    """Return first numeric value found in or after the row containing keyword."""
    for i, row in enumerate(rows):
        joined = " ".join(_texts(row)).lower()
        if keyword.lower() in joined:
            for t in _texts(row):
                if keyword.lower() not in t.lower():
                    v = _parse_float(t)
                    if v is not None:
                        return v
            for next_row in rows[i + 1: i + 4]:
                for t in _texts(next_row):
                    v = _parse_float(t)
                    if v is not None:
                        return v
    return None


# ---------------------------------------------------------------------------
# Image type detection
# ---------------------------------------------------------------------------

def detect_image_type(rows: list) -> str:
    all_text = " ".join(_all_tokens(rows)).upper()
    if "TRIGGER" in all_text and "STOP" in all_text:
        return "stop_orders"
    if "AVAIL VOL" in all_text or ("AVAIL" in all_text and "SIDE" not in all_text):
        return "stocks"
    if "SIDE" in all_text and ("SHORT" in all_text or "LONG" in all_text):
        return "futures"
    return "unknown"


# ---------------------------------------------------------------------------
# Stop orders parser
# ---------------------------------------------------------------------------

def parse_stop_orders(rows: list) -> dict:
    header_idx = None
    for i, row in enumerate(rows):
        ts = _texts(row)
        has_symbol = any("Symbol" in t for t in ts)
        has_side = any("Side" in t for t in ts)
        if has_symbol and has_side:
            header_idx = i
            break

    if header_idx is None:
        return _empty("stop_orders")

    stop_orders = []
    for row in rows[header_idx + 1:]:
        ts = _texts(row)
        # Drop "Stop" tokens (Type column), header leftovers, and empty
        filtered = [t for t in ts if t not in {"Stop", "Type", "Condition", "Volume", "Symbol", "Side"} and t.strip()]
        if len(filtered) < 3:
            continue

        symbol = _clean_symbol(filtered[0])
        # Apply normalization if it looks like a misread S50 future
        if re.match(r'^(SS[O0]|S5O|SS50)', symbol.upper()):
            symbol = _normalise_futures_symbol(symbol)
            
        side = filtered[1] if len(filtered) > 1 else ""

        # Find condition token (contains "Last")
        condition_raw = next((t for t in filtered[2:] if "last" in t.lower()), "")
        condition = re.sub(r'[Ll]ast\s*([<>])\s*=', lambda m: f"Last {m.group(1)}=", condition_raw)

        # Find trigger price inside parentheses e.g. "Trigger Price (17.10)"
        trigger_str = next((t for t in filtered if "Trigger" in t or "trigger" in t), "")
        m = re.search(r'\(([\d.]+)\)', trigger_str)
        trigger_price = float(m.group(1)) if m else None

        # Volume = last numeric token that is not the trigger price
        volume = None
        for t in reversed(filtered):
            v = _parse_float(t)
            if v is not None and v != trigger_price:
                volume = v
                break

        if symbol and trigger_price is not None:
            stop_orders.append({
                "symbol": symbol,
                "side": side,
                "type": "Stop",
                "trigger_price": trigger_price,
                "volume": volume,
            })

    return {
        "image_type": "stop_orders",
        "stop_orders": stop_orders,
        "holdings": [],
        "total_amount": None,
        "line_available": None,
    }


# ---------------------------------------------------------------------------
# Stocks holdings parser
# ---------------------------------------------------------------------------

_SKIP_STOCKS = {
    "Total", "Close", "Amount", "Market", "Value", "Unrealized", "Realized",
    "Trading", "Line", "Available", "Cash", "Balance", "SBI", "Buy", "Sell",
    "Portfolio", "Services", "More", "May", "Avg", "Sort", "All", "Order",
    "Deal", "Sum", "Portfolios", "Symbol", "Avail", "Vol", "UPL", "%UPL",
    "Realtime", "Login", "Last",
}

_BADGE_TOKENS = {"CA", "XD", "XR", "SP", "NP"}


def parse_stocks(rows: list) -> dict:
    header_idx = next(
        (i for i, row in enumerate(rows)
         if "Symbol" in _texts(row) and any("Avail" in t for t in _texts(row))),
        None,
    )
    if header_idx is None:
        return _empty("stocks")

    holdings = []
    pending_ts = []
    
    for row in rows[header_idx + 1:]:
        ts = _texts(row)
        if not ts:
            continue
        first = ts[0]
        joined = " ".join(ts)

        # Stop at summary section
        if any(kw in joined for kw in ["Total", "Amount", "Login", "SET ", "Trading", "Line Available"]):
            break
            
        if _is_numeric(first):
            if pending_ts:
                ts = pending_ts + ts
                first = ts[0]
            else:
                continue
                
        if first in _SKIP_STOCKS:
            continue

        symbol = _clean_symbol(first)
        nums = []
        for t in ts[1:]:
            if t in _BADGE_TOKENS or not t:
                continue
            v = _parse_float(t)
            if v is not None:
                nums.append(v)

        if len(nums) >= 4:
            holdings.append({
                "symbol": symbol,
                "side": "",
                "amount": nums[0],   # avail_vol
                "avg": nums[1],
                "market": nums[2],
                "upnl_pct": nums[3],
            })
            pending_ts = []
        elif len(nums) == 3:
            # Possibly OCR missed volume (e.g. NFC SP misread) — flag with None
            holdings.append({
                "symbol": symbol,
                "side": "",
                "amount": None,      # OCR error — needs review
                "avg": nums[0],
                "market": nums[1],
                "upnl_pct": nums[2],
            })
            pending_ts = []
        else:
            # Not enough numbers, keep tokens for next row merging
            pending_ts = [t for t in ts if not _is_numeric(t) and t not in _BADGE_TOKENS]

    total_amount = _find_value_after_keyword(rows, "Amount")
    line_available = _find_value_after_keyword(rows, "Line Available")

    return {
        "image_type": "stocks",
        "holdings": holdings,
        "total_amount": total_amount,
        "line_available": line_available,
        "stop_orders": [],
    }


# ---------------------------------------------------------------------------
# Futures holdings parser
# ---------------------------------------------------------------------------

_SKIP_FUTURES = {
    "Total", "Share", "Trading", "Credit", "Home", "Portfolio",
    "Content", "You", "Avg", "Summary", "All", "Port", "Order",
    "Symbol", "Side", "Vol", "Market", "%UPL",
}


def parse_futures(rows: list) -> dict:
    header_idx = next(
        (i for i, row in enumerate(rows)
         if "Symbol" in _texts(row) and "Side" in _texts(row) and "Vol" in _texts(row)),
        None,
    )
    if header_idx is None:
        return _empty("futures")

    holdings = []
    pending_ts = []
    for row in rows[header_idx + 1:]:
        ts = _texts(row)
        if not ts:
            continue
        first = ts[0]
        joined = " ".join(ts)

        if any(kw in joined for kw in ["Total", "Trading", "Credit", "Equity", "SET ", "Share"]):
            break
            
        if _is_numeric(first):
            if pending_ts:
                ts = pending_ts + ts
                first = ts[0]
            else:
                continue
                
        if first in _SKIP_FUTURES:
            continue

        symbol = _normalise_futures_symbol(_clean_symbol(first))
        side = next((t for t in ts[1:] if t in {"Long", "Short", "Buy", "Sell"}), "")
        nums = [_parse_float(t) for t in ts[1:] if _is_numeric(t)]

        if len(nums) >= 4:
            holdings.append({
                "symbol": symbol,
                "side": side,
                "amount": nums[0],   # vol
                "avg": nums[1],
                "market": nums[2],
                "upnl_pct": nums[3],
            })
            pending_ts = []
        else:
            pending_ts = [t for t in ts if not _is_numeric(t)]

    # Excess Equity = total_amount for futures account
    total_amount = _find_value_after_keyword(rows, "Excess")

    return {
        "image_type": "futures",
        "holdings": holdings,
        "total_amount": total_amount,
        "line_available": None,
        "stop_orders": [],
    }


def _clean_symbol(s: str) -> str:
    """Remove parenthetical suffixes like (SP), (CA), (XD) from symbol names."""
    return re.sub(r'\s*\([^)]*\)', '', s).strip()


def _normalise_futures_symbol(raw: str) -> str:
    """Fix common OCR misreads in futures symbols (e.g. S50k26 → S50K26)."""
    s = raw.upper()
    # O/0 confusion at specific positions, s/5 confusion
    s = re.sub(r'^SS[O0]', 'S50', s)   # SSOM26, SS0M26 → S50M26
    s = re.sub(r'^S5O', 'S50', s)      # S5OM26 → S50M26
    s = re.sub(r'^SS50', 'S50', s)
    
    # Continuously replace 'O' with '0' if it's immediately preceded by a digit
    # This fixes strike prices like 1OOO -> 1000
    while re.search(r'\dO', s):
        s = re.sub(r'(\d)O', r'\g<1>0', s)
        
    s = re.sub(r'(?<=[A-Z])O(?=\d)', '0', s)   # trailing O that should be 0
    return s


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_image(image_path: str) -> dict:
    """Run OCR on image and return structured SBI data."""
    ocr_results = run_ocr(image_path)
    rows = group_rows(ocr_results)
    image_type = detect_image_type(rows)

    parsers = {
        "stop_orders": parse_stop_orders,
        "stocks": parse_stocks,
        "futures": parse_futures,
    }
    parser = parsers.get(image_type)
    if parser:
        return parser(rows)
    return _empty("unknown")


def _empty(image_type: str) -> dict:
    return {
        "image_type": image_type,
        "holdings": [],
        "stop_orders": [],
        "total_amount": None,
        "line_available": None,
    }
