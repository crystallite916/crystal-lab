import os
import sys

# Ensure project root is on path for tests that are run from the repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import expenses_automation.main as main


def test_simple_amount():
    body = "Your bill is $12.34. Please pay by the due date."
    amt = main.extract_amount(body)
    assert round(amt, 2) == 12.34


def test_total_vs_tax():
    body = "Subtotal $20.00\nTax $4.00\nTotal $24.00"
    amt = main.extract_amount(body)
    assert round(amt, 2) == 24.00


def test_amount_with_usd_prefix():
    body = "Amount due USD 123.45 as of today."
    amt = main.extract_amount(body)
    # New behavior: only $-prefixed amounts are recognized
    assert amt is None


def test_prefers_amount_due_over_other_numbers():
    body = "Invoice 2025-001\nAmount due $75.00\nRef: 24"
    amt = main.extract_amount(body)
    assert round(amt, 2) == 75.00


def test_no_amount_returns_none():
    body = "This email has no currency numbers or amounts."
    assert main.extract_amount(body) is None


def test_prefers_currency_symbol_when_no_keywords():
    # Two amounts, one with $ symbol, no clear keywords — prefer the $ one
    body = "Charge A 12.00\nCharge B $24.00"
    amt = main.extract_amount(body)
    assert round(amt, 2) == 24.00


def test_extract_amount_debug_returns_candidates():
    body = "Subtotal $20.00\nTotal $24.00"
    res = main.extract_amount(body, debug=True)
    assert isinstance(res, dict)
    assert round(res["value"], 2) == 24.00
    assert "candidates" in res and len(res["candidates"]) >= 1
