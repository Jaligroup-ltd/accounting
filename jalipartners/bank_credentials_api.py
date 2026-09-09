"""Credential distribution API for the bank feed microservices.

Reads the "Bank Credential" DocType, whose fieldnames are the environment
variable names themselves (IMBANK_USERNAME, BK_PASSWORD, ...), and hands them
to the scrapers over loopback.

Fields are discovered from the DocType meta, not hard-coded here: any Data or
Password field whose fieldname is UPPER_SNAKE_CASE is treated as a credential.
Adding a fifth bank later means adding two fields in the UI and two lines to
CREDENTIAL_MAP in credentials.py - no change to this file.

Authentication is a normal Frappe API key/secret belonging to a dedicated
service user, sent as:

    Authorization: token <api_key>:<api_secret>

That user must hold the "Bank Credential Manager" role and should have its
"Restrict IP" field set to 127.0.0.1. There is deliberately no `allow_guest`
endpoint - the site answers on the public internet.
"""

import hashlib
import re

import frappe
from frappe import _
from frappe.utils import now_datetime

CRED_DOCTYPE = "Bank Credential"
CRED_ROLE = "Bank Credential Manager"

# Which fields count as credentials.
#
# Any Password-type field qualifies outright - on this doctype a Password field
# is a credential by definition. Data fields qualify when the name ends in a
# credential-ish word, which is what lets a fifth bank be added in the UI with
# no change here. Matching is case-insensitive: Frappe lowercases fieldnames
# generated from labels, so IMBANK_USERNAME becomes imbank_username.
CRED_NAME_PATTERN = re.compile(
    r"(?:^|_)(username|user|password|passwd|pass|secret|login)$", re.I
)
CREDENTIAL_FIELDTYPES = ("Data", "Password")


def _guard():
    user = frappe.session.user
    if not user or user == "Guest":
        raise frappe.PermissionError(_("Authentication required."))
    if user == "Administrator":
        return
    if CRED_ROLE not in frappe.get_roles(user):
        raise frappe.PermissionError(_("Not permitted to read bank credentials."))


def _fingerprint(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def _get_credential_doc(docname=None):
    """Return the document holding the credentials.

    Works whether "Bank Credential" is a Single doctype or a normal one with a
    single record. With more than one record, the caller must name it.
    """
    meta = frappe.get_meta(CRED_DOCTYPE)

    if meta.issingle:
        return frappe.get_doc(CRED_DOCTYPE)

    if docname:
        return frappe.get_doc(CRED_DOCTYPE, docname)

    names = frappe.get_all(CRED_DOCTYPE, pluck="name", limit=2)
    if not names:
        frappe.throw(_("No Bank Credential record exists yet."))
    if len(names) > 1:
        frappe.throw(
            _("More than one Bank Credential record exists. Make the DocType Single, "
              "or set ERP_CREDENTIAL_DOC in the scraper .env to name the one to use.")
        )
    return frappe.get_doc(CRED_DOCTYPE, names[0])


def _is_credential_field(df):
    if df.fieldtype == "Password":
        return True
    if df.fieldtype == "Data" and CRED_NAME_PATTERN.search(df.fieldname or ""):
        return True
    return False


def _credential_fieldnames(meta):
    """[(fieldname, ENV_VAR_NAME, fieldtype)] for every credential field."""
    return [
        (df.fieldname, (df.fieldname or "").upper(), df.fieldtype)
        for df in meta.fields
        if _is_credential_field(df)
    ]


@frappe.whitelist()
def ping():
    """Connectivity + auth probe, and a field-discovery report.

    `matched` is what will be sent; `skipped` is every other Data/Password field
    with the reason, so a fieldname that does not qualify is obvious here rather
    than showing up as a silently missing credential later.
    """
    _guard()
    meta = frappe.get_meta(CRED_DOCTYPE)

    matched = [
        {"field": fn, "env_var": env, "type": ft}
        for fn, env, ft in _credential_fieldnames(meta)
    ]
    skipped = [
        {"field": df.fieldname, "type": df.fieldtype}
        for df in meta.fields
        if df.fieldtype in CREDENTIAL_FIELDTYPES and not _is_credential_field(df)
    ]

    if not meta.issingle:
        record_count = frappe.db.count(CRED_DOCTYPE)
    else:
        record_count = None

    return {
        "ok": True,
        "user": frappe.session.user,
        "doctype": CRED_DOCTYPE,
        "is_single": bool(meta.issingle),
        "records": record_count,
        "matched": matched,
        "skipped": skipped,
        "time": str(now_datetime()),
    }


@frappe.whitelist()
def get_credentials(docname=None):
    """Return credentials keyed by environment variable name.

    Response shape:
        {
          "ok": true,
          "count": 8,
          "values": {"IMBANK_USERNAME": "...", "IMBANK_PASSWORD": "...", ...}
        }

    Blank fields are omitted rather than returned empty, so an unfilled field in
    ERPNext leaves the scraper's existing .env value alone instead of wiping it.
    """
    _guard()

    doc = _get_credential_doc(docname)
    meta = frappe.get_meta(CRED_DOCTYPE)

    values = {}
    for fieldname, env_var, fieldtype in _credential_fieldnames(meta):
        if fieldtype == "Password":
            value = doc.get_password(fieldname, raise_exception=False)
        else:
            value = doc.get(fieldname)

        value = (value or "").strip()
        if value:
            values[env_var] = value

    frappe.logger("bank_credentials").info(
        {"event": "credentials_served", "user": frappe.session.user, "fields": sorted(values)}
    )

    return {"ok": True, "count": len(values), "values": values}


@frappe.whitelist()
def get_fingerprints(docname=None):
    """Same as get_credentials but without the secrets - safe to log.

    Use it to answer "did someone change a password since the last good run?"
    """
    _guard()

    payload = get_credentials(docname)
    return {
        "ok": True,
        "fingerprints": {k: _fingerprint(v) for k, v in payload["values"].items()},
    }