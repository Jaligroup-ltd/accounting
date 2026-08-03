"""
bank_feed_api.py — Frappe server methods for triggering per-bank statement fetches from the
Bank Reconciliation Tool. The feed is inferred from the SELECTED Bank Account (no dropdown):
each feed lists the exact Bank Account name(s) it reconciles.

Place in your app (e.g. jalipartners/jalipartners/bank_feed_api.py). site_config.json must
carry:  "bank_feed_service_token": "<the same value as the services' BANK_FEED_SERVICE_TOKEN>"
"""

import frappe
import requests

# --- registry -------------------------------------------------------------- #
# value (key) -> label + local service + the exact ERPNext Bank Account name(s)
# this feed reconciles. Selecting one of those accounts is what picks the feed.
BANK_FEEDS = {
    "imbank": {
        "label": "I&M Bank",
        "service_url": "http://127.0.0.1:8899/fetch",
        "accounts": ["IM Bank account - IM Bank"],
    },
    "bkbank": {
        "label": "Bank of Kigali",
        "service_url": "http://127.0.0.1:8898/fetch",
        "accounts": ["BK Bank - BK"],
    },
    "mtnmomo": {
        "label": "MTN MoMo",
        "service_url": "http://127.0.0.1:8897/fetch",
        "accounts": ["MTN MoMo Account - MTN MoMo"],
    },
}

# dotted path to _run_fetch for frappe.enqueue. Derived from this module's real import
# path (__name__), so it's correct wherever the file is placed — no manual matching.
_RUN_FETCH_PATH = f"{__name__}._run_fetch"


def _service_token():
    token = frappe.conf.get("bank_feed_service_token")
    if not token:
        frappe.throw("bank_feed_service_token is not set in site_config.json")
    return token


def _feed_for_account(bank_account):
    """Return the feed key whose registry lists this Bank Account, else None."""
    for key, cfg in BANK_FEEDS.items():
        if bank_account in cfg.get("accounts", []):
            return key
    return None


@frappe.whitelist()
def get_bank_feeds():
    """Banks available to fetch (kept for reference / any manual UI)."""
    return [{"value": key, "label": cfg["label"]} for key, cfg in BANK_FEEDS.items()]


@frappe.whitelist()
def feed_label_for_account(bank_account):
    """Return the feed's label for a Bank Account, or None if it has no feed.
    The Client Script uses this to show/hide the Fetch button per selected account."""
    key = _feed_for_account(bank_account)
    return BANK_FEEDS[key]["label"] if key else None


@frappe.whitelist()
def trigger_fetch_for_account(bank_account, from_date=None, to_date=None):
    """Resolve the feed from the selected Bank Account and queue its fetch."""
    key = _feed_for_account(bank_account)
    if not key:
        frappe.throw(f"No bank feed is configured for Bank Account '{bank_account}'.")
    return trigger_fetch(key, from_date=from_date, to_date=to_date)


@frappe.whitelist()
def trigger_fetch(bank, from_date=None, to_date=None):
    """Queue a fetch for `bank`. Returns immediately; completion arrives via realtime."""
    if bank not in BANK_FEEDS:
        frappe.throw(f"Unknown bank feed: {bank}")
    frappe.enqueue(
        _RUN_FETCH_PATH,
        queue="long",
        timeout=1500,
        bank=bank,
        from_date=from_date,
        to_date=to_date,
        user=frappe.session.user,
    )
    return {"queued": True, "bank": bank, "label": BANK_FEEDS[bank]["label"]}


def _run_fetch(bank, from_date, to_date, user):
    """Background job: call the bank's local service, then notify the user."""
    feed = BANK_FEEDS[bank]
    try:
        resp = requests.post(
            feed["service_url"],
            json={"from_date": from_date, "to_date": to_date},
            headers={"Authorization": f"token {_service_token()}"},
            timeout=1200,
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        created = data.get("created")
        made = f"{created} new transaction(s)" if created is not None else "done"
        notify_fetch_done(user, bank, ok=True, message=f"{feed['label']}: {made}")
    except Exception as e:
        notify_fetch_done(user, bank, ok=False, message=f"{feed['label']} fetch failed: {e}")
        raise


def notify_fetch_done(user, bank, ok, message):
    """Realtime toast to the triggering user. after_commit=False so it fires reliably."""
    frappe.publish_realtime(
        "bank_feed_done",
        {"bank": bank, "ok": ok, "message": message},
        user=user,
        after_commit=False,
    )