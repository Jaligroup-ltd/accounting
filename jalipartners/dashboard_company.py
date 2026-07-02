import frappe

@frappe.whitelist()

def set_dashboard_company(company):
    frappe.defaults.set_user_default("Company", company)
    return company