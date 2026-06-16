import base64
import os
import re
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter
import sys
sys.path.insert(0, r"C:\Git\credentials")
from central_creds import get_credentials
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SENDER = "no-reply@liberatorsec.co.th"
TMP_DIR = Path(tempfile.gettempdir()) / "lib"


def _get_gmail_service():
    creds = get_credentials(SCOPES)
    return build("gmail", "v1", credentials=creds)


def _get_recent_emails_with_pdf(service, max_results=5) -> list[dict]:
    results = service.users().messages().list(
        userId="me",
        q=f"from:{SENDER} has:attachment filename:pdf",
        maxResults=max_results,
    ).execute()

    messages = results.get("messages", [])
    full_messages = []
    for msg in messages:
        full_msg = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="full",
        ).execute()
        full_messages.append(full_msg)
    return full_messages


def _download_pdf(service, message: dict) -> bytes | None:
    parts = message["payload"].get("parts", [])
    for part in parts:
        if part.get("filename", "").lower().endswith(".pdf") and "attachmentId" in part.get("body", {}):
            att = service.users().messages().attachments().get(
                userId="me",
                messageId=message["id"],
                id=part["body"]["attachmentId"],
            ).execute()
            return base64.urlsafe_b64decode(att["data"])
    return None


def _decrypt_pdf(pdf_path: Path, password: str) -> Path:
    reader = PdfReader(str(pdf_path))
    reader.decrypt(password)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    decrypted_path = pdf_path.parent / "statement_decrypted.pdf"
    with open(decrypted_path, "wb") as f:
        writer.write(f)
    return decrypted_path


def _extract_ending_cash_balance(pdf_path: str) -> float:
    """Extract Ending Cash Balance from a text-based PDF using pdfplumber."""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    if not text.strip():
        raise ValueError("PDF contains no extractable text")

    # Split the text by account header
    sections = re.split(r'(?:เลขที่บัญชี\s+ประเภทบัญชี|Account\s+No\s+Account\s+Type)', text)
    
    # If splitting didn't yield multiple sections, treat the whole document as one section
    sections_to_process = sections[1:] if len(sections) > 1 else [text]
    
    total_balance = 0.0
    found_any = False

    for section in sections_to_process:
        # Check if there is a Margin Summary
        margin_match = re.search(
            r'Margin\s+Summary\s*\n\s*Ending\s+Unrealized\s+Equity[^\n]*\n\s*Cash\s+Balance[^\n]*\n\s*(-?[\d,]+\.\d{2})',
            section,
            re.IGNORECASE
        )
        
        balance = None
        if margin_match:
            val_str = margin_match.group(1).replace(",", "")
            balance = float(val_str)
            found_any = True
        else:
            # Look for Cash Balance C/F (ยอดเงินยกไป)
            cf_match = re.search(
                r'ยอดเงินยกไป\s+(-?[\d,]+\.\d{2})\s*\n\s*Cash\s+Balance\s+C/F',
                section,
                re.IGNORECASE
            )
            if cf_match:
                val_str = cf_match.group(1).replace(",", "")
                balance = float(val_str)
                found_any = True
            else:
                # Strategy 2 fallback: "Ending Cash Balance" label appears near the value on the same line
                match = re.search(
                    r'Ending\s+Cash\s+Balance[^\d\n\-]*(-?[\d,]+\.\d{2})',
                    section, re.IGNORECASE,
                )
                if match:
                    val_str = match.group(1).replace(",", "")
                    balance = float(val_str)
                    found_any = True
                
        if balance is not None:
            total_balance += balance

    if not found_any:
        raise ValueError(
            "Could not find any Cash Balance C/F or Margin Summary in PDF. "
            "The retrieved email might be a trade confirmation rather than a statement."
        )

    return total_balance


def fetch() -> dict:
    print("  [LIB] Connecting to Gmail...")
    service = _get_gmail_service()

    print(f"  [LIB] Searching for recent emails from {SENDER}...")
    messages = _get_recent_emails_with_pdf(service, max_results=5)
    if not messages:
        raise ValueError(f"No emails with PDF found from {SENDER}")

    balance = None
    for idx, message in enumerate(messages):
        print(f"  [LIB] Processing email {idx+1}/{len(messages)}...")
        pdf_bytes = _download_pdf(service, message)
        if not pdf_bytes:
            print("  [LIB] No PDF attachment found in this email, skipping.")
            continue

        TMP_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = TMP_DIR / "statement.pdf"
        pdf_path.write_bytes(pdf_bytes)

        password = os.getenv("LIB_PDF_PASSWORD", "").strip()
        if password:
            try:
                pdf_path = _decrypt_pdf(pdf_path, password)
            except Exception as e:
                print(f"  [LIB] Failed to decrypt PDF: {e}. Skipping.")
                continue

        try:
            balance = _extract_ending_cash_balance(str(pdf_path))
            print(f"  [LIB] Ending Cash Balance: {balance:,.2f}")
            break
        except ValueError as e:
            print("  [LIB] Not a valid statement, skipping to next email.")

    if balance is None:
        raise ValueError("Could not find a valid Cash Balance Statement in the recent emails.")

    return {
        "platform": "LIB",
        "ending_cash_balance": balance,
    }
