import frappe
import requests
from datetime import date

@frappe.whitelist()
def get_exchange_rate(from_currency, to_currency, transaction_date=None, args=None):
    """
    Custom exchange rate fetcher with RWF support.
    Falls back to Frankfurter for major currency pairs.
    """
    if not transaction_date:
        transaction_date = str(date.today())

    # First check if a manual record exists
    existing = frappe.db.get_value(
        "Currency Exchange",
        {"from_currency": from_currency, "to_currency": to_currency, "date": transaction_date},
        "exchange_rate"
    )
    if existing:
        return existing

    # RWF pairs: use open.er-api.com (free, no key needed)
    RWF_CURRENCIES = {"RWF"}
    
    if from_currency in RWF_CURRENCIES or to_currency in RWF_CURRENCIES:
        return _fetch_rwf_rate(from_currency, to_currency, transaction_date)
    
    # All other pairs: use Frankfurter as normal
    try:
        url = f"https://api.frankfurter.dev/v1/{transaction_date}?from={from_currency}&to={to_currency}"
        r = requests.get(url, timeout=5)
        data = r.json()
        return data["rates"].get(to_currency)
    except Exception:
        frappe.log_error("Frankfurter API failed", "Currency Exchange")
        return None


def _fetch_rwf_rate(from_currency, to_currency, transaction_date):
    """Fetch RWF rate and cache it as a Currency Exchange record."""
    try:
        base = from_currency if from_currency != "RWF" else to_currency
        url = f"https://open.er-api.com/v6/latest/{base}"
        r = requests.get(url, timeout=5)
        data = r.json()
        
        target = to_currency if from_currency != "RWF" else from_currency
        rate = data["rates"].get(target)
        
        if rate:
            # Invert if we fetched the wrong direction
            final_rate = rate if from_currency != "RWF" else (1 / rate)
            
            # Cache it
            doc = frappe.new_doc("Currency Exchange")
            doc.from_currency = from_currency
            doc.to_currency = to_currency
            doc.exchange_rate = final_rate
            doc.date = transaction_date
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            
            return final_rate
    except Exception as e:
        frappe.log_error(str(e), "RWF Exchange Rate Fetch Failed")
        return None