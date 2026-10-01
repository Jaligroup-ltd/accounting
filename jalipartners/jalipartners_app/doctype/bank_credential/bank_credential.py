"""Controller for the Bank Credential DocType (one document per Company).

Passwords use the Frappe `Password` fieldtype on the child rows, so the
plaintext never lands in `tabCompany Bank Credential` - it is encrypted into
`__Auth` keyed by the child row's name.

That keying has a consequence worth knowing: deleting a row and re-adding it
does NOT carry the password across, because the new row gets a new name. To
retire a feed, untick `enabled` rather than deleting the row. `on_trash` of the
parent is blocked by permissions for the same reason.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class BankCredential(Document):
    def validate(self):
        self._check_no_duplicate_feeds()
        self._check_bank_account_company()
        self._check_enabled_rows_are_complete()

    def _check_no_duplicate_feeds(self):
        seen = set()
        for row in self.credentials or []:
            if row.bank_feed in seen:
                frappe.throw(
                    _("Row {0}: {1} appears more than once. One row per bank feed per company.")
                    .format(row.idx, frappe.bold(row.bank_feed))
                )
            seen.add(row.bank_feed)

    def _check_bank_account_company(self):
        """A statement must not be posted to another company's Bank Account."""
        for row in self.credentials or []:
            if not row.bank_account:
                continue
            owner = frappe.db.get_value("Bank Account", row.bank_account, "company")
            if owner and owner != self.company:
                frappe.throw(
                    _("Row {0}: Bank Account {1} belongs to {2}, not {3}.")
                    .format(row.idx, frappe.bold(row.bank_account),
                            frappe.bold(owner), frappe.bold(self.company))
                )

    def _check_enabled_rows_are_complete(self):
        """An enabled row must be usable, or the scrape will be refused at run time.

        Credentials come only from ERPNext now - there is no .env fallback - so a
        row missing a username or a Bank Account is a run that cannot happen.
        Mailbox feeds (the OTP inboxes) legitimately have no Bank Account.
        """
        for row in self.credentials or []:
            if not row.enabled:
                continue

            if not row.username:
                frappe.throw(
                    _("Row {0}: {1} is enabled but has no username.")
                    .format(row.idx, frappe.bold(row.bank_feed))
                )

            if self._is_mailbox(row.bank_feed):
                continue

            if not row.bank_account:
                frappe.throw(
                    _("Row {0}: {1} is enabled but has no Bank Account. "
                      "Set it, or untick Enabled - the import has nowhere to post "
                      "this feed's transactions otherwise.")
                    .format(row.idx, frappe.bold(row.bank_feed))
                )

    @staticmethod
    def _is_mailbox(bank_feed):
        if not bank_feed:
            return False
        return bool(frappe.db.get_value("Bank Feed", bank_feed, "is_mailbox"))