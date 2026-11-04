import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    for fieldname in ("custom_ebm_generated_at", "custom_ebm_response"):
        name = frappe.db.get_value("Custom Field", {"dt": "Sales Invoice", "fieldname": fieldname})
        if name:
            frappe.delete_doc("Custom Field", name)

    create_custom_fields({
        "Sales Invoice": [
            dict(fieldname="custom_ebm_section", label="EBM", fieldtype="Section Break",
                 insert_after="remarks", collapsible=1),
            dict(fieldname="custom_ebm_invoice_number", label="EBM Invoice Number", fieldtype="Data",
                 read_only=1, no_copy=1, allow_on_submit=1, insert_after="custom_ebm_section"),
        ]
    })