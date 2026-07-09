"""
bank_feed_api.py — Frappe server methods for triggering per-bank statement fetches from the
Bank Reconciliation Tool (generalises the old imbank_feed_api.py to any number of banks).

Each bank's automation runs as its own localhost FastAPI service (the same "separate
microservice, never embedded in Frappe" pattern as I&M). This module only dispatches to them.

To add a bank: add ONE entry to BANK_FEEDS below. The reconciliation-tool dropdown and the
dispatch both read from it — no other change needed.

Place this in your app (e.g. jalipartners/jalipartners/bank_feed_api.py) and make the dotted
path in the Client Script (BANK_FEED_API) match where it lives.

site_config.json (or common_site_config.json) must carry the shared secret both this module
and the bank services use:
    "bank_feed_service_token": "<long random string>"
"""

import frappe
import requests

# --- registry -------------------------------------------------------------- #
# value (key) -> label shown in the dropdown + the local service that does the work.
# Each service must expose: POST {service_url}  body {from_date, to_date}
#                           header Authorization: token <bank_feed_service_token>
#                           returns JSON like {"ok": true, "created": <n>}
BANK_FEEDS = {
    "imbank": {"label": "I&M Bank",        "service_url": "http://127.0.0.1:8899/fetch"},
    "bkbank": {"label": "Bank of Kigali",  "service_url": "http://127.0.0.1:8898/fetch"},
    # "equity": {"label": "Equity Bank",   "service_url": "http://127.0.0.1:8897/fetch"},
}

# dotted path to _run_fetch for frappe.enqueue. Derived from this module's real import
# path (__name__), so it's correct wherever the file is placed — no manual matching.
_RUN_FETCH_PATH = f"{__name__}._run_fetch"

def _service_token():
    token = frappe.conf.get("bank_feed_service_token")
    if not token:
        frappe.throw("bank_feed_service_token is not set in site_config.json")
    return token


@frappe.whitelist()
def get_bank_feeds():
    """Banks available to fetch — feeds the reconciliation-tool dropdown."""
    return [{"value": key, "label": cfg["label"]} for key, cfg in BANK_FEEDS.items()]


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