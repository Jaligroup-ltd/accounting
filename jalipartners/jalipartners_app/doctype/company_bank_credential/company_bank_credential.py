"""Child table row: one bank feed's credentials for one company.

Validation lives on the parent (Bank Credential), which can see the company
and therefore check that the Bank Account belongs to it.
"""

from frappe.model.document import Document


class CompanyBankCredential(Document):
    pass
