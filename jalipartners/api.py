"""
jalipartners/api.py  —  ERPNext server-side glue for the I&M bank feed.

Add these methods to your existing `jalipartners` app:
    place this content in: apps/jalipartners/jalipartners/api.py
    (if api.py already exists, append these two methods + helpers to it)

Exposes two whitelisted methods:
  - trigger_fetch(from_date, to_date): the button calls this; it enqueues a
    background job that POSTs to the local bank_automation service.
  - notify_fetch_done(success, detail): the service calls this when finished,
    and we push a realtime toast to the user.

Config (set in site_config.json):
    imbank_service_url   default "http://127.0.0.1:8899"
    imbank_service_token must match SERVICE_TOKEN in bank_automation/.env
"""

import frappe
import requests


def _service_url():
    return (frappe.conf.get("imbank_service_url")
            or "http://127.0.0.1:8899").rstrip("/")


def _service_token():
    token = frappe.conf.get("imbank_service_token")
    if not token:
        frappe.throw("imbank_service_token is not set in site_config.json.")
    return token


@frappe.whitelist()
def trigger_fetch(from_date, to_date):
    """Called by the Bank Reconciliation page button.

    Enqueues a background job so the HTTP call to the scraper service doesn't
    block the web worker (the scrape can take 30-60s). Returns immediately.
    """
    # Basic guard: only users who can create Bank Transactions should trigger.
    if not frappe.has_permission("Bank Transaction", "create"):
        frappe.throw("You don't have permission to import bank transactions.")

    if not from_date or not to_date:
        frappe.throw("From Date and To Date are required.")

    frappe.enqueue(
        "jalipartners.api._do_fetch",
        queue="long",
        timeout=600,
        from_date=str(from_date),
        to_date=str(to_date),
        user=frappe.session.user,
    )
    return {"status": "queued", "from_date": str(from_date),
            "to_date": str(to_date)}


def _do_fetch(from_date, to_date, user):
    """Runs in the background worker: calls the local scraper service."""
    try:
        resp = requests.post(
            f"{_service_url()}/fetch",
            headers={"Authorization": f"Bearer {_service_token()}"},
            json={"from_date": from_date, "to_date": to_date},
            timeout=30,
        )
        if resp.status_code == 409:
            _toast(user, "A fetch is already running. Try again shortly.",
                   indicator="orange")
            return
        resp.raise_for_status()
        # Success here only means the run STARTED; the service will call
        # notify_fetch_done when the scrape+import actually completes.
        _toast(user, "I&M fetch started , you'll be notified when it's done.",
               indicator="blue")
    except Exception as e:
        frappe.log_error(f"imbank trigger_fetch failed: {e}", "imbank_feed")
        _toast(user, f"Could not start I&M fetch: {e}", indicator="red")


@frappe.whitelist(allow_guest=False)
def notify_fetch_done(success=False, detail=""):
    """Called by the bank_automation service when a run finishes.

    Authenticated via the API key/secret the service already uses, so it maps
    to a real ERPNext user. We push a realtime event that the browser shows.
    """
    success = frappe.parse_json(success) if isinstance(success, str) else success
    msg = ("I&M import complete , click 'Get Unreconciled Entries'."
           if success else f"I&M import failed: {detail}")
    # Publish immediately (after_commit=False): this API call doesn't write to
    # the DB, so there's no commit to wait for — after_commit=True would mean
    # the event never fires. Broadcast to everyone; the client filters by event.
    frappe.publish_realtime(
        event="imbank_feed_done",
        message={"success": bool(success), "detail": detail, "msg": msg},
        after_commit=False,
    )
    frappe.db.commit()  # flush so socketio delivers without delay
    return {"ok": True}


def _toast(user, message, indicator="blue"):
    """Push a transient message to a specific user's browser session(s)."""
    frappe.publish_realtime(
        event="imbank_feed_toast",
        message={"message": message, "indicator": indicator},
        user=user,
        after_commit=False,
    )