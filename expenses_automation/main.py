import base64
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

# Path to your shared credential file (outside repo)
CREDENTIALS_PATH = "/Users/crystalsun/Documents/crystal-lab/credentials/credentials.json"


# Path inside your repo (project-specific token)
TOKEN_PATH = "./token.json"

# Google Sheets info
SPREADSHEET_ID = "17ZeK2aj9_BEyYhegAm-pgZ7K0KlB6pWBerg2fi38nBk"
EXPENSES_RANGE = "expenses!A:J"
VENDORS_RANGE = "vendors!A:E"
PROPOSED_RANGE = "proposed_expenses!A:F"

# Limit processing to this sender (change as desired)
TARGET_SENDER = "noreply@billing.coned.com"

# Name of label to add to messages we've processed to avoid re-processing
LABEL_NAME = "ExpensesProcessed"

# OAuth scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    # Needed to add labels and modify messages
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",
]


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------


def get_credentials():
    """Load shared credentials.json and local token.json."""
    creds = None

    # Load token if it exists
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If creds exist, ensure they include the scopes we need.
    def _scopes_sufficient(c):
        return c is not None and set(SCOPES).issubset(set(getattr(c, "scopes", []) or []))

    # If no valid credentials available, or scopes are insufficient, trigger login flow
    if not creds or not _scopes_sufficient(creds) or not creds.valid:
        # If expired and we have a refresh token, try refreshing first (but refresh won't add scopes)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                # Refresh failed; we'll run the flow below
                creds = None

        # If scopes still insufficient or no creds, run the full flow to get user consent for new scopes
        if not _scopes_sufficient(creds):
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token.json inside the project
        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    return creds


# --------------------------------------------------
# GMAIL HELPERS
# --------------------------------------------------


# Simple regex to capture amounts with a leading '$' only (e.g. $1,234.56)
DOLLAR_AMOUNT_RE = re.compile(r"(?ix)\$\s*([0-9]{1,3}(?:[,0-9]{3})*(?:\.[0-9]{1,2})?)")

CONTEXT_WINDOW = 120  # characters on either side to look for keywords


def _to_decimal(s: str):
    """Helper: convert numeric string with commas to Decimal, or raise."""
    if s is None:
        raise InvalidOperation("None passed")
    normalized = s.replace(",", "").strip()
    return Decimal(normalized)


def extract_amount(body: str, debug: bool = False):
    """
    Find and return the best candidate monetary amount from the email body as a Decimal.
    Heuristics:
      1) find all amounts
      2) score them by proximity to keywords
      3) prefer higher-weight keywords, then larger amounts, then last occurrence
    Returns Decimal or None if nothing found.
    """
    if not body or not isinstance(body, str):
        return None

    # Normalize whitespace for easier searching
    normalized_body = " ".join(body.split())

    # Find all matches and their positions
    candidates = []
    # Find all dollar-prefixed amounts (simple behavior per new requirement)
    for m in DOLLAR_AMOUNT_RE.finditer(normalized_body):
        found = m.group(1)
        try:
            dec_val = _to_decimal(found)
        except InvalidOperation:
            continue

        start, end = m.span()
        candidates.append(
            {
                "value": dec_val,
                "start": start,
                "end": end,
                "matched_text": normalized_body[start:end],
            }
        )

    if not candidates:
        return None if not debug else {"value": None, "candidates": []}

    # Simple selection: choose the last dollar-prefixed amount in the message
    # (commonly the 'total' appears later than subtotals/taxes)
    best = candidates[-1]

    if debug:
        # Return both numeric value and candidate details for debugging
        return {
            "value": float(best["value"]),
            "best": best,
            "candidates": candidates,
        }

    return float(best["value"])


def get_email_body(msg):
    """Extract plain text from Gmail message parts."""
    payload = msg.get("payload", {})

    # If message body is directly provided
    if "data" in payload.get("body", {}):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    # Otherwise look for plaintext part
    for part in payload.get("parts", []):
        if part["mimeType"] == "text/plain":
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    return ""


# --------------------------------------------------
# SHEETS HELPERS
# --------------------------------------------------


def get_vendors(sheets):
    """Load the Vendors sheet into a dict keyed by domain."""
    result = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=VENDORS_RANGE).execute()

    rows = result.get("values", [])[1:]  # skip header

    vendors = {}
    for r in rows:
        # Make sure row has all expected fields
        if len(r) < 5:
            continue

        name, domain, who, payer, active = r

        vendors[domain.lower()] = {
            "vendor_name": name,
            "default_who": who,
            "default_payer": payer,
            "active": active.lower() == "true",
        }

    return vendors


def get_or_create_label(gmail, label_name: str):
    """Return Gmail label id for label_name; create it if it doesn't exist."""
    labels_resp = gmail.users().labels().list(userId="me").execute()
    labels = labels_resp.get("labels", [])
    for lab in labels:
        if lab.get("name") == label_name:
            return lab.get("id")

    # create label
    body = {
        "name": label_name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }
    created = gmail.users().labels().create(userId="me", body=body).execute()
    return created.get("id")


def append_to_expenses(sheets, data):
    sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=EXPENSES_RANGE,
        valueInputOption="USER_ENTERED",
        body={"values": [data]},
    ).execute()


def append_to_proposed(sheets, data):
    sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=PROPOSED_RANGE,
        valueInputOption="USER_ENTERED",
        body={"values": [data]},
    ).execute()


# --------------------------------------------------
# MAIN LOGIC
# --------------------------------------------------


def main():
    creds = get_credentials()

    gmail = build("gmail", "v1", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds).spreadsheets()

    vendors = get_vendors(sheets)

    # Debug mode toggle
    debug_mode = os.getenv("EXPENSES_DEBUG") is not None

    # Ensure label exists and get its id
    label_id = get_or_create_label(gmail, LABEL_NAME)

    # Fetch the most recent 100 messages
    # Limit to messages from TARGET_SENDER and exclude already-processed messages
    query = f"from:{TARGET_SENDER} -label:{LABEL_NAME}"
    messages = (
        gmail.users()
        .messages()
        .list(userId="me", maxResults=100, q=query)
        .execute()
        .get("messages", [])
    )

    if debug_mode:
        print(f"DEBUG: Using query: {query}")
        print(f"DEBUG: Found {len(messages) if messages else 0} messages matching query")
        if not messages:
            print(
                "DEBUG: No messages returned. Possible reasons: no messages from target sender, or all messages are already labeled as processed."
            )

    for m in messages:
        try:
            if debug_mode:
                print(f"DEBUG: Processing message id={m.get('id')}")
            msg = gmail.users().messages().get(userId="me", id=m["id"]).execute()

            # Extract headers
            headers = msg["payload"]["headers"]
            from_header = next((h["value"] for h in headers if h["name"] == "From"), "").lower()

            if debug_mode:
                # print a short snippet of the message body to help debugging
                snippet = (msg.get("snippet") or "")[:200]
                print(f"DEBUG: From header: {from_header}")
                print(f"DEBUG: Snippet: {snippet!r}")

            body = get_email_body(msg)
            debug_mode = os.getenv("EXPENSES_DEBUG") is not None
            amt_result = extract_amount(body, debug=debug_mode)
            # amt_result may be a float (normal) or dict (debug)
            if debug_mode:
                if isinstance(amt_result, dict):
                    amount = amt_result.get("value")
                    # Print debug info
                    print(f"DEBUG: Message {m['id']} candidates:")
                    for c in amt_result.get("candidates", []):
                        print(
                            f"  - {c['matched_text']} -> value={c['value']} score={c.get('score'):.2f} context={c['context'][:80]!r}"
                        )
                    print(
                        f"  Chosen: {amt_result.get('best', {}).get('matched_text')} -> {amt_result.get('value')}"
                    )
                else:
                    amount = amt_result
            else:
                amount = amt_result
            date = datetime.utcfromtimestamp(int(msg["internalDate"]) / 1000).strftime("%Y-%m-%d")

            # Identify known vendor by email domain match
            matched_vendor = None
            for domain, vdata in vendors.items():
                if domain in from_header:
                    matched_vendor = vdata
                    break

            # ------------------------------
            # CASE 1 → Known Vendor
            # ------------------------------
            if matched_vendor and amount:
                if matched_vendor["active"]:
                    append_to_expenses(
                        sheets,
                        [
                            matched_vendor["vendor_name"],
                            date,
                            f"{matched_vendor['vendor_name']} bill",
                            amount,
                            matched_vendor["default_payer"],
                            matched_vendor["default_who"],
                            "",
                            "",
                            "",
                            "FALSE",
                        ],
                    )
                else:
                    append_to_proposed(
                        sheets,
                        [matched_vendor["vendor_name"], date, amount, body[:200], m["id"], "new"],
                    )

            # ------------------------------
            # CASE 2 → Unknown Vendor
            # ------------------------------
            elif amount:
                append_to_proposed(
                    sheets, ["Unknown Vendor", date, amount, body[:200], m["id"], "new"]
                )

            # Mark message as processed (add label) so it won't be re-processed
            gmail.users().messages().modify(
                userId="me", id=m["id"], body={"addLabelIds": [label_id]}
            ).execute()

        except Exception as e:
            print(f"Error processing message {m.get('id')}: {e}")
            # Do not label the message if processing failed so it can be retried
            continue

    print("Done.")


# --------------------------------------------------
# RUN
# --------------------------------------------------
if __name__ == "__main__":
    main()
