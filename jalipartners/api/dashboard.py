import frappe

@frappe.whitelist()
def set_dashboard_company(company=None):
    if company:
        frappe.defaults.set_user_default("jali_dashboard_company", company)
    else:
        frappe.defaults.clear_user_default("jali_dashboard_company")
    return company or ""