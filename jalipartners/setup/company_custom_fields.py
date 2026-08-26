# jalipartners/setup/company_custom_fields.py
#
# Defines the Company custom fields the invoice print format depends on.
# Run via after_migrate hook so they exist on every site / after every update.
#
# WHY THIS FILE EXISTS:
#   Editing the core Company DocType directly (DocType > Company) does NOT
#   survive an ERPNext version bump — your fields get wiped. Custom Fields
#   created in code + exported as fixtures do survive.

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


COMPANY_CUSTOM_FIELDS = {
    "Company": [
        {
            "fieldname": "company_registration_no",
            "label": "Company Registration No",
            "fieldtype": "Data",
            "insert_after": "tax_id",
            "description": "RDB registration number, printed in the invoice footer.",
        },
        {
            "fieldname": "company_registered_office",
            "label": "Registered Office",
            "fieldtype": "Small Text",
            "insert_after": "company_registration_no",
            "description": "Registered office address, printed in the invoice footer.",
        },
    ]
}


def execute():
    create_custom_fields(COMPANY_CUSTOM_FIELDS, update=True)
    frappe.db.commit()