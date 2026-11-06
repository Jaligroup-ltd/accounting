import re

import frappe
import requests

from jalipartners.huza_sync import _cfg  # also loads the .env file

SMS_ENV_KEYS = ("INTOUCH_SEND_SMS_URL", "INTOUCH_USERNAME", "INTOUCH_PASSWORD", "INTOUCH_SENDER")


def _local_phone(raw):
    """+250788354222 -> 0788354222 (the format in the Intouch sample)."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("250") and len(d) == 12:
        return "0" + d[3:]
    if len(d) == 9:
        return "0" + d
    return d


def _error_text(body):
    try:
        err = body["response"][0]["errors"]
        return err.get("error") or err.get("action")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def send_sms(phone, message):
    """Send one SMS through Intouch. Returns (ok, error_text)."""
    try:
        r = requests.post(
            _cfg("INTOUCH_SEND_SMS_URL"),
            auth=(_cfg("INTOUCH_USERNAME"), _cfg("INTOUCH_PASSWORD")),
            files={  # multipart form, like curl --form
                "recipients": (None, _local_phone(phone)),
                "sender": (None, _cfg("INTOUCH_SENDER")),
                "message": (None, message),
            },
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        frappe.log_error(str(e), "Intouch SMS request failed")
        return False, "could not reach the SMS provider"

    try:
        body = r.json()
    except ValueError:
        body = {}

    if r.status_code < 400 and isinstance(body, dict) and body.get("success") is True:
        return True, None

    frappe.log_error(f"HTTP {r.status_code}\n{r.text[:1000]}", "Intouch SMS rejected")
    return False, _error_text(body) or f"HTTP {r.status_code}"