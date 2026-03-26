import frappe

@frappe.whitelist()
def get_user_permitted_company():
    """Return the company this user is permitted to access"""
    if frappe.session.user == "Administrator":
        return None

    # Check User Permission
    permitted = frappe.get_all(
        "User Permission",
        filters={
            "user": frappe.session.user,
            "allow": "Company"
        },
        fields=["for_value"],
        limit=1,
        ignore_permissions=True  # needed so non-admin can call this
    )

    if permitted:
        return permitted[0].for_value

    # Fallback to User Default
    return frappe.defaults.get_user_default("company")


def set_user_company(doc, method):
    """Auto-set company on validate and before_insert"""
    if not hasattr(doc, "company"):
        return
    if frappe.session.user == "Administrator":
        return

    user_company = get_user_permitted_company()
    if not user_company:
        return

    if not doc.company:
        doc.company = user_company