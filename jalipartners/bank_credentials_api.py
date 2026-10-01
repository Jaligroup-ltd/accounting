"""Credential distribution API for the bank feed microservices.

Serves one company's bank logins, plus the Bank Account each feed's
transactions should be posted to, from the "Bank Credential" DocType.

Fields are explicit (`bank_feed`, `username`, `password`, `bank_account`), so
there is no fieldname guessing: adding a bank is a new Bank Feed record plus a
row, with no change to this file.

Authentication is a normal Frappe API key/secret belonging to a dedicated
service user, sent as:

    Authorization: token <api_key>:<api_secret>

That user must hold the "Bank Credential Manager" role and should have its
"Restrict IP" field set to 127.0.0.1. There is deliberately no `allow_guest`
endpoint - the site answers on the public internet.
"""

import hashlib

import frappe
from frappe import _
from frappe.utils import now_datetime

CRED_DOCTYPE = "Bank Credential"
CRED_ROLE = "Bank Credential Manager"


def _guard():
    user = frappe.session.user
    if not user or user == "Guest":
        raise frappe.PermissionError(_("Authentication required."))
    if user == "Administrator":
        return
    if CRED_ROLE not in frappe.get_roles(user):
        raise frappe.PermissionError(_("Not permitted to read bank credentials."))


def _fingerprint(*parts):
    raw = "\x00".join(p or "" for p in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _resolve_company(company=None):
    """Return the Bank Credential document name to read.

    With a company given, use it. Without one, fall back to the only enabled
    record - which keeps single-company installs from needing any config.
    """
    if company:
        if not frappe.db.exists(CRED_DOCTYPE, company):
            frappe.throw(_("No Bank Credential record for company {0}.").format(company))
        return company

    names = frappe.get_all(CRED_DOCTYPE, filters={"enabled": 1}, pluck="name", limit=2)
    if not names:
        frappe.throw(_("No enabled Bank Credential record exists."))
    if len(names) > 1:
        frappe.throw(
            _("Several companies have credentials. Pass a company, or set "
              "ERP_COMPANY in the scraper .env.")
        )
    return names[0]


@frappe.whitelist()
def ping(company=None):
    """Connectivity, auth, and a configuration report for one company."""
    _guard()

    try:
        name = _resolve_company(company)
    except frappe.ValidationError as exc:
        return {
            "ok": False,
            "user": frappe.session.user,
            "error": str(exc),
            "companies": frappe.get_all(CRED_DOCTYPE, pluck="name"),
        }

    doc = frappe.get_doc(CRED_DOCTYPE, name)
    rows = []
    for row in doc.credentials or []:
        pwd = row.get_password("password", raise_exception=False)
        rows.append({
            "bank_feed": row.bank_feed,
            "enabled": bool(row.enabled),
            "has_username": bool(row.username),
            "has_password": bool(pwd),
            "bank_account": row.bank_account or None,
            "currency": row.currency or None,
        })

    return {
        "ok": True,
        "user": frappe.session.user,
        "company": doc.company,
        "company_enabled": bool(doc.enabled),
        "rows": rows,
        "time": str(now_datetime()),
    }


@frappe.whitelist()
def list_companies():
    """Every company with credentials, for a scheduler that loops them."""
    _guard()
    records = frappe.get_all(
        CRED_DOCTYPE, fields=["name as company", "enabled"], order_by="company asc"
    )
    return {
        "ok": True,
        "companies": [r["company"] for r in records if r.get("enabled")],
        "all": records,
    }


@frappe.whitelist()
def get_credentials(company=None):
    """Return one company's feeds.

    Response shape:
        {"ok": true, "company": "Jali Group Ltd", "count": 3,
         "feeds": {
            "imbank": {"username": "...", "password": "...",
                       "bank_account": "I&M Current-OD - JK", "currency": ""},
            ...
         }}

    Rows that are disabled, or missing a username or password, are omitted
    rather than returned empty - so an incomplete row leaves the scraper's
    existing .env value alone instead of wiping it.
    """
    _guard()

    name = _resolve_company(company)
    doc = frappe.get_doc(CRED_DOCTYPE, name)

    if not doc.enabled:
        return {"ok": True, "company": doc.company, "count": 0, "feeds": {},
                "note": "company disabled"}

    feeds = {}
    for row in doc.credentials or []:
        if not row.enabled:
            continue
        password = row.get_password("password", raise_exception=False) or ""
        username = (row.username or "").strip()
        if not username or not password:
            continue
        feeds[row.bank_feed] = {
            "username": username,
            "password": password,
            "bank_account": row.bank_account or "",
            "currency": row.currency or "",
            "fingerprint": _fingerprint(username, password, row.bank_account),
        }

    _stamp_fetch(name)
    frappe.logger("bank_credentials").info(
        {"event": "credentials_served", "user": frappe.session.user,
         "company": doc.company, "feeds": sorted(feeds)}
    )

    return {"ok": True, "company": doc.company, "count": len(feeds), "feeds": feeds}


@frappe.whitelist()
def get_fingerprints(company=None):
    """The same keys with hashes instead of secrets - safe to log.

    Use it to answer "did someone change a password since the last good run?"
    """
    _guard()
    payload = get_credentials(company)
    return {
        "ok": True,
        "company": payload.get("company"),
        "fingerprints": {k: v["fingerprint"] for k, v in payload["feeds"].items()},
    }


def _stamp_fetch(name):
    """Record that the service pulled this company's credentials. Best effort."""
    try:
        frappe.db.set_value(CRED_DOCTYPE, name, "last_fetched_on", now_datetime(),
                            update_modified=False)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "bank_credentials: last_fetched_on failed")