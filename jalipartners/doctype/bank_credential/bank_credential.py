"""Controller for the Bank Credential DocType.

Stores the login credentials used by the bank scraper microservices.
Passwords use the Frappe `Password` fieldtype, so the plaintext never lives in
`tabBank Credential` - it is encrypted into the `__Auth` table with the site's
`encryption_key` and can only be read back through `doc.get_password()`.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

FEED_KEY_PATTERN = re.compile(r"^[a-z0-9_]{2,40}$")


class BankCredential(Document):
    def validate(self):
        self.feed_key = (self.feed_key or "").strip().lower()
        if not FEED_KEY_PATTERN.match(self.feed_key):
            frappe.throw(
                _("Feed Key must be lower-case letters, digits or underscores (e.g. imbank, bk, mtnmomo, zoho).")
            )

        if self.username:
            self.username = self.username.strip()

        if not self.label:
            self.label = self.feed_key

        if self._password_was_changed():
            self.last_rotated_on = now_datetime()

    def _password_was_changed(self):
        """A loaded doc carries asterisks in the password field until it is edited."""
        value = self.get("password") or ""
        if not value:
            return False
        return set(value) != {"*"}
