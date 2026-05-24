import frappe
import requests
from datetime import date


@frappe.whitelist()
def get_exchange_rate(from_currency, to_currency, transaction_date=None, args=None):
    """
    Custom exchange rate fetcher with RWF support.
    Falls back to Frankfurter for non-RWF pairs.
    """
    # Guard 1: missing inputs
    if not from_currency or not to_currency:
        return 1.0

    # Guard 2: same currency → rate is always 1, never hit any API or insert a record
    if from_currency == to_currency:
        return 1.0

    if not transaction_date:
        transaction_date = str(date.today())

    # Reuse a manual/cached record if one exists
    existing = frappe.db.get_value(
        "Currency Exchange",
        {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "date": transaction_date,
        },
        "exchange_rate",
    )
    if existing:
        return existing

    # RWF pairs → open.er-api.com (Frankfurter doesn't support RWF)
    if "RWF" in (from_currency, to_currency):
        return _fetch_rwf_rate(from_currency, to_currency, transaction_date)

    # Everything else → Frankfurter
    try:
        url = f"https://api.frankfurter.dev/v1/{transaction_date}?from={from_currency}&to={to_currency}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json().get("rates", {}).get(to_currency)
    except Exception as e:
        frappe.log_error(f"Frankfurter failed for {from_currency}->{to_currency}: {e}", "Currency Exchange")
        return None


def _fetch_rwf_rate(from_currency, to_currency, transaction_date):
    """Fetch a rate involving RWF from open.er-api.com and cache it."""
    # Defensive: must never be called with equal currencies
    if from_currency == to_currency:
        return 1.0

    try:
        # Always fetch using the non-RWF side as the base, then invert if needed
        base = to_currency if from_currency == "RWF" else from_currency
        target = from_currency if from_currency == "RWF" else to_currency

        url = f"https://open.er-api.com/v6/latest/{base}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()

        rate = data.get("rates", {}).get(target)
        if not rate:
            return None

        final_rate = (1 / rate) if from_currency == "RWF" else rate

        # Cache it — only insert when currencies differ (belt-and-braces)
        if from_currency != to_currency:
            doc = frappe.new_doc("Currency Exchange")
            doc.from_currency = from_currency
            doc.to_currency = to_currency
            doc.exchange_rate = final_rate
            doc.date = transaction_date
            doc.insert(ignore_permissions=True)
            frappe.db.commit()

        return final_rate
    except Exception as e:
        frappe.log_error(f"RWF rate fetch failed {from_currency}->{to_currency}: {e}", "Currency Exchange")
        return None