import frappe

TITLES = {"A": "A-Exempt", "B": "B-Tax", "C": "C-Export", "D": "D-Non VAT"}
RATES = {"A": 0, "B": 18, "C": 0, "D": 0}


def setup_ebm_tax_templates(company, vat_account):
    """Create or fix the four EBM Item Tax Templates for one company, plus an 'EBM VAT' sales tax template.
    Existing templates with the same title and company get their tax rows replaced."""
    if not frappe.db.exists("Account", {"name": vat_account, "company": company}):
        frappe.throw(f"Account {vat_account} not found in company {company}")

    for code, title in TITLES.items():
        name = frappe.db.get_value("Item Tax Template", {"title": title, "company": company}, "name")
        doc = frappe.get_doc("Item Tax Template", name) if name else frappe.new_doc("Item Tax Template")
        doc.title = title
        doc.company = company
        doc.set("taxes", [{"tax_type": vat_account, "tax_rate": RATES[code]}])
        doc.save() if name else doc.insert()

    if not frappe.db.exists("Sales Taxes and Charges Template", {"title": "EBM VAT", "company": company}):
        has_default = frappe.db.exists(
            "Sales Taxes and Charges Template", {"company": company, "is_default": 1})
        frappe.get_doc({
            "doctype": "Sales Taxes and Charges Template",
            "title": "EBM VAT",
            "company": company,
            "is_default": 0 if has_default else 1,
            "taxes": [{
                "charge_type": "On Net Total",
                "account_head": vat_account,
                "description": "VAT",
                "rate": 0,  # per-item templates set the real rate (18 for B)
            }],
        }).insert()
    frappe.db.commit()
    return "done"


def check_item_taxes(company, items):
    """Show each item's tax rows and which template ERPNext would pick for an invoice in this company."""
    from erpnext.stock.get_item_details import get_item_tax_template

    result = {}
    for code in items:
        item = frappe.get_doc("Item", code)
        out = {}
        get_item_tax_template(frappe._dict(company=company, tax_category=None), item, out)
        result[code] = {
            "rows": [[r.item_tax_template, r.tax_category] for r in item.taxes],
            "picks": out.get("item_tax_template"),
        }
    return result