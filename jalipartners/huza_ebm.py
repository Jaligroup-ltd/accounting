import json
import os
import random
import re
from datetime import timedelta
from html import escape
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import cint, flt, now_datetime, validate_email_address

from jalipartners.huza_sync import _cfg, fetch_huza_items
from jalipartners.intouch_sms import SMS_ENV_KEYS, send_sms

SERIES_KEY = "EBM-INV-"
# Tax rate per Huza/RRA tax code. Verify against the RRA code table.
TAX_RATE = {"A": 0.0, "B": 18.0, "C": 0.0, "D": 0.0}


def _money(v):
    return f"{flt(v):.2f}"


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _phone(raw):
    d = _digits(raw)
    if not d:
        return ""
    if d.startswith("250") and len(d) == 12:
        return "+" + d
    if len(d) == 10 and d.startswith("0"):
        return "+250" + d[1:]
    if len(d) == 9:
        return "+250" + d
    return "+" + d


# ---------------------------------------------------------------------------
# Entry point (called from the "Generate EBM Invoice" menu entry)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def generate_ebm_invoice(sales_invoice, purchase_code=None, customer_tin=None, customer_phone=None,
                         customer_email=None, send_sms=0, send_email=0):
    if not frappe.db.has_column("Sales Invoice", "custom_ebm_invoice_number"):
        frappe.throw(_(
            "The 'EBM Invoice Number' field is missing on Sales Invoice. "
            "Ask an administrator to run the jalipartners EBM field patch."
        ))

    want_sms, want_email = cint(send_sms), cint(send_email)

    # Row lock: a second click or user waits here until we commit, then sees the saved EBM number
    frappe.db.get_value("Sales Invoice", sales_invoice, "name", for_update=True)
    doc = frappe.get_doc("Sales Invoice", sales_invoice)
    doc.check_permission("submit")
    _validate(doc)

    phone, tin, code = _resolve_party(doc, customer_tin, purchase_code, customer_phone)
    email = _check_notifications(customer_email, want_sms, want_email)

    huza_items = {i["itemCd"]: i for i in fetch_huza_items()}
    invoice_number = int(getseries(SERIES_KEY, 1))  # rolled back automatically if we throw below
    payload = _build_payload(doc, huza_items, invoice_number, phone, tin, code)

    try:
        status_code, body = _post_to_huza(payload)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        frappe.log_error(json.dumps(payload, indent=2), f"Huza EBM no response: {doc.name}")
        frappe.throw(_(
            "Huza did not respond. The invoice may or may not have been registered. "
            "Check Huza for invoice number {0} before trying again."
        ).format(invoice_number))

    if status_code >= 400 or (isinstance(body, dict) and body.get("status") not in (None, "Success", True)):
        frappe.log_error(
            f"HTTP {status_code}\n{json.dumps(body, indent=2)}\n\nPayload:\n{json.dumps(payload, indent=2)}",
            f"Huza EBM rejected: {doc.name}",
        )
        msg = body.get("message") if isinstance(body, dict) else None
        frappe.throw(_("Huza rejected the invoice: {0}").format(msg or f"HTTP {status_code}"))

    link = _receipt_link(body)

    # Huza accepted it: make sure this invoice number is never reused, even if saving below fails
    frappe.db.commit()
    try:
        doc.db_set("custom_ebm_invoice_number", str(invoice_number), update_modified=False)
        comment = _("EBM invoice {0} generated in Huza").format(invoice_number)
        if link:
            comment += f' (<a href="{escape(link)}" target="_blank">{_("receipt")}</a>)'
        doc.add_comment("Info", comment)
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"EBM invoice {invoice_number} registered in Huza but not saved: {doc.name}",
        )
        frappe.throw(_(
            "Huza registered EBM invoice {0}, but it could not be saved on this Sales Invoice. "
            "Do not send it again. Contact an administrator."
        ).format(invoice_number))

    notifications = _notify(doc, invoice_number, payload["total"], phone, email, want_sms, want_email, link)
    return {"invoice_number": invoice_number, "notifications": notifications, "receipt_link": link}


# ---------------------------------------------------------------------------
# Validation and party details
# ---------------------------------------------------------------------------

def _validate(doc):
    if doc.docstatus != 1:
        frappe.throw(_("Submit the Sales Invoice before generating an EBM invoice."))
    if doc.is_return:
        frappe.throw(_("Credit notes are not supported yet."))
    if doc.get("custom_ebm_invoice_number"):
        frappe.throw(_("EBM invoice {0} was already generated for this invoice.").format(
            doc.custom_ebm_invoice_number))
    if doc.currency != frappe.get_cached_value("Company", doc.company, "default_currency"):
        frappe.throw(_("EBM invoices can only be generated in the company currency."))


def _resolve_party(doc, customer_tin, purchase_code, customer_phone=None):
    """Company customers: TIN and purchase code come from the dialog.
    Individuals: TIN from the customer (or last 9 digits of the phone), purchase code 000000.
    Huza requires a phone number in both cases."""
    customer = frappe.db.get_value(
        "Customer", doc.customer, ["customer_type", "tax_id", "mobile_no"], as_dict=True)
    phone = _phone(customer_phone or doc.get("contact_mobile") or customer.mobile_no)
    if len(_digits(phone)) < 9:
        frappe.throw(_(
            "Huza requires a customer phone number. Enter one in the dialog, "
            "or add a mobile number to the contact of customer {0}."
        ).format(doc.customer))

    if customer.customer_type == "Company":
        tin = _digits(customer_tin)
        code = (purchase_code or "").strip()
        if not code or code == "000000":
            frappe.throw(_("A purchase code different from 000000 is required for company customers."))
    else:
        tin = _digits(customer.tax_id) or _digits(phone)[-9:]
        code = "000000"

    if len(tin) != 9:
        frappe.throw(_(
            "The customer TIN must be 9 digits (got '{0}'). "
            "Set the Tax ID or a mobile number on customer {1}."
        ).format(tin, doc.customer))
    return phone, tin, code


def _check_notifications(customer_email, want_sms, want_email):
    """Fail early (before anything is sent to Huza) if a requested channel cannot work."""
    email = (customer_email or "").strip()
    if want_email and not validate_email_address(email):
        frappe.throw(_("Enter a valid customer email address to send the invoice by email."))
    if want_sms:
        for key in SMS_ENV_KEYS:
            _cfg(key)  # throws a clear "X is not configured" message
    return email


# ---------------------------------------------------------------------------
# Huza payload
# ---------------------------------------------------------------------------

def _build_payload(doc, huza_items, invoice_number, phone, tin, purchase_code):
    missing = sorted({i.item_code for i in doc.items if i.item_code not in huza_items})
    if missing:
        frappe.throw(_(
            "These items do not exist in Huza (the ERPNext item code must equal the Huza itemCd): {0}. "
            "Run 'Sync from Huza' on the Item list and use the synced items on the invoice."
        ).format(", ".join(missing)))

    # If ERPNext adds tax on top (tax rows with an amount), net_amount is tax-exclusive.
    # Otherwise net_amount already includes tax.
    exclusive = flt(doc.total_taxes_and_charges) > 0

    # 1. Tax-inclusive amount per line (RRA works on inclusive amounts)
    rows = []
    for it in doc.items:
        h = huza_items[it.item_code]
        code = h.get("taxTyCd")
        if code not in TAX_RATE:
            frappe.throw(_("Unknown EBM tax code '{0}' on item {1}").format(code, it.item_code))
        rate = TAX_RATE[code]
        qty = flt(it.qty)
        net = flt(it.net_amount)
        gross = flt(net * (1 + rate / 100), 2) if exclusive else flt(net, 2)
        unit = flt(gross / qty, 2) if qty else 0.0
        gross = flt(unit * qty, 2)  # keep unit price x quantity = amount exactly
        rows.append({"h": h, "code": code, "rate": rate, "qty": qty, "unit": unit, "gross": gross, "tax": 0.0})

    # 2. Tax per tax code from the group total: tax = inclusive amount x rate / (100 + rate).
    #    The rounding difference goes on the last line so lines add up to the group tax.
    groups = {}
    for r in rows:
        groups.setdefault(r["code"], []).append(r)
    for code, group in groups.items():
        rate = TAX_RATE[code]
        group_tax = flt(sum(r["gross"] for r in group) * rate / (100 + rate), 2)
        allocated = 0.0
        for r in group[:-1]:
            r["tax"] = flt(r["gross"] * rate / (100 + rate), 2)
            allocated += r["tax"]
        group[-1]["tax"] = flt(group_tax - allocated, 2)

    total = flt(sum(r["gross"] for r in rows), 2)
    total_tax = flt(sum(r["tax"] for r in rows), 2)

    if abs(total - flt(doc.grand_total)) > 1:
        frappe.throw(_(
            "EBM total {0} does not match the invoice total {1}. "
            "Check the taxes on the invoice and the tax codes of its items."
        ).format(total, doc.grand_total))

    lines = []
    for r in rows:
        h = r["h"]
        lines.append({
            "name": h.get("itemNm"),
            "item_classification_code": h.get("itemClsCd"),
            "packaging_unit_code": h.get("pkgUnitCd"),
            "package": "1",
            "quantity": _money(r["qty"]),
            "uom": h.get("qtyUnitCd"),
            "rate": _money(r["unit"]),             # tax-inclusive unit price
            "isrcRt": h.get("isrcRt") or "0.00",
            "bcd": h.get("bcd"),
            "isrcAmt": h.get("isrcAmt") or "0.00",
            "isrccNm": h.get("isrccNm"),
            "isrccCd": h.get("isrccCd"),
            "amount": _money(r["gross"]),          # tax-inclusive line amount
            "item_code": h.get("itemCd"),
            "item_type_code": h.get("itemTyCd"),
            "tax_type": r["code"],
            "tax_rate": _money(r["rate"]),
            "taxable_amount": _money(r["gross"]),  # RRA: taxable amount = inclusive amount
            "tax_amount": _money(r["tax"]),
            "discount_rate": "0",
            "discount_amount": "0",
        })

    # Paid / balance, based on the amount the customer actually owes (rounded total if any)
    payable = flt(doc.rounded_total) or flt(doc.grand_total)
    if flt(doc.outstanding_amount) < 0.5:  # fully paid (within rounding)
        paid = total
    else:
        paid = max(0.0, flt(payable - flt(doc.outstanding_amount), 2))
    balance = flt(total - paid, 2)

    now = now_datetime()

    return {
        "original_invoice_number": "0",
        "sender": doc.company,
        "recipient": doc.customer_name,
        "recipient_phone_number": phone,
        "customer_tin": tin,
        "purchase_code": purchase_code,
        "sales_type_code": "N",
        "receipt_type_code": "S",
        "payment_type_code": "01",
        "invoice_status_code": "01",
        "validated_date": now.strftime("%Y%m%d%H%M%S"),
        "date": now.strftime("%Y%m%d"),
        "due_date": (now + timedelta(days=7)).strftime("%Y%m%d"),
        "notes": f"Notes for #{doc.customer_name}",
        "terms": f"Terms & Conditions for #{doc.customer_name}",
        "subtotal": _money(total),
        "total": _money(total),
        "tax": _money(total_tax),
        "taxable_amount": _money(total),
        "discount": "0",
        "amount_paid": _money(paid),
        "balance_due": _money(balance),
        "registrant_id": "SYSTEM",
        "registrant_name": "SYSTEM",
        "modifier_name": "SYSTEM",
        "modifier_id": "SYSTEM",
        "print_size": "A4",
        "report_number": str(random.randint(100000, 999999999)),
        "items": lines,
        "invoice_number": invoice_number,
    }


def _post_to_huza(payload):
    r = requests.post(
        f"{_cfg('HUZA_BASE_URL').rstrip('/')}/invoices",
        json=payload,
        headers={"Authorization": f"Bearer {_cfg('HUZA_API_TOKEN')}", "Accept": "application/json"},
        timeout=45,
    )
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:2000]}
    return r.status_code, body


# ---------------------------------------------------------------------------
# Notifications (run only after Huza accepted the invoice, never raise)
# ---------------------------------------------------------------------------

def _receipt_link(body):
    """Huza returns the receipt PDF URL in data.file_path."""
    data = body.get("data") if isinstance(body, dict) else None
    link = data.get("file_path") if isinstance(data, dict) else None
    if not (isinstance(link, str) and link.startswith(("http://", "https://"))):
        return None

    # Optional: swap the host when Huza returns an internal address such as http://localhost:8080
    public_base = os.environ.get("HUZA_RECEIPT_BASE_URL")
    if public_base:
        p = urlparse(link)
        link = public_base.rstrip("/") + p.path + (f"?{p.query}" if p.query else "")
    return link


def _shorten_link(link):
    """Shorten the receipt URL with TinyURL (used for the SMS only).
    Returns the original link if TinyURL is not configured or fails, so the SMS is never blocked."""
    token = os.environ.get("TINYURL_API_TOKEN")
    if not token:
        return link
    try:
        r = requests.post(
            "https://api.tinyurl.com/create",
            json={"url": link, "domain": os.environ.get("TINYURL_DOMAIN", "tinyurl.com")},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        body = r.json()
        short = (body.get("data") or {}).get("tiny_url") if isinstance(body, dict) else None
        if r.status_code < 400 and short:
            return short
        frappe.log_error(f"HTTP {r.status_code}\n{r.text[:500]}", "TinyURL rejected")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "TinyURL request failed")
    return link


def _sms_text(doc, invoice_number, total, link):
    # Kept short so it fits in one or two SMS segments
    return f"{doc.company}: invoice no. {invoice_number}, {doc.currency} {flt(total):,.2f}. View: {link}"


def _send_email(doc, email, invoice_number, total, link):
    button = (
        "display:inline-block;padding:10px 18px;background:#1a73e8;color:#ffffff;"
        "text-decoration:none;border-radius:4px;"
    )
    message = (
        f"<p>Dear {escape(doc.customer_name or '')},</p>"
        f"<p>Your invoice no. <b>{invoice_number}</b> from {escape(doc.company)} "
        f"({escape(doc.currency)} {flt(total):,.2f}) is ready.</p>"
        f'<p><a href="{escape(link)}" style="{button}">View your invoice</a></p>'
        # f"<p>If the button does not work, copy this link into your browser:<br>{escape(link)}</p>"
        "<p>Thank you.</p>"
    )
    frappe.sendmail(
        recipients=[email],
        subject=_("Your invoice from {0}").format(doc.company),
        message=message,
        reference_doctype="Sales Invoice",
        reference_name=doc.name,
        now=True,
    )

    # sendmail() does not raise when emails are muted or the queue is held, so check the outcome
    queued = frappe.get_all(
        "Email Queue",
        filters={"reference_doctype": "Sales Invoice", "reference_name": doc.name},
        fields=["status", "error"],
        order_by="creation desc",
        limit=1,
    )
    status = queued[0].status if queued else None
    if status == "Sent":
        return True, None
    if status == "Error":
        lines = (queued[0].error or "").strip().splitlines()
        return False, (lines[-1][:200] if lines else _("email server error"))
    return False, _("the email was not sent (emails are disabled or paused on this site)")


def _safe(fn, *args):
    """A failed SMS or email must never look like a failed invoice."""
    try:
        return fn(*args)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "EBM notification failed")
        return False, str(e)[:200] or "unexpected error"


def _notify(doc, invoice_number, total, phone, email, want_sms, want_email, link):
    result, notes = {}, []

    if (want_sms or want_email) and not link:
        error = _("Huza did not return a receipt link")
        frappe.log_error(f"No data.file_path in the Huza response for {doc.name}", "EBM receipt link missing")
        for key, label, wanted in (("sms", "SMS", want_sms), ("email", "Email", want_email)):
            if wanted:
                result[key] = {"ok": False, "error": error}
                notes.append(f"{label} not sent: {error}")
    else:
        if want_sms:
            sms_link = _shorten_link(link)  # SMS gets the short link, email keeps the full one
            ok, error = _safe(send_sms, phone, _sms_text(doc, invoice_number, total, sms_link))
            result["sms"] = {"ok": ok, "error": error}
            notes.append(f"SMS sent to {phone}" if ok else f"SMS failed: {error}")
        if want_email:
            ok, error = _safe(_send_email, doc, email, invoice_number, total, link)
            result["email"] = {"ok": ok, "error": error}
            notes.append(f"Email sent to {email}" if ok else f"Email failed: {error}")

    if notes:
        try:
            doc.add_comment("Info", "; ".join(notes))
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "EBM notification comment failed")
    return result


# ---------------------------------------------------------------------------
# Hook: an invoice that was fiscalized cannot be cancelled
# ---------------------------------------------------------------------------

def block_cancel_if_fiscalized(doc, method=None):
    if doc.get("custom_ebm_invoice_number"):
        frappe.throw(_("EBM invoice {0} was issued for this invoice, so it cannot be cancelled.").format(
            doc.custom_ebm_invoice_number))