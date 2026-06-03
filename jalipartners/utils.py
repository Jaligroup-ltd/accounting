import frappe
from frappe import _


# =====================================================================
# Constants
# =====================================================================

ALLOWED_ROLE_PROFILES = [
    "Super Admin",
    "Company Admin",
    "Company Staff",
    "Company Basic",
]

COMPANY_SCOPED_PROFILES = [
    "Company Admin",
    "Company Staff",
    "Company Basic",
]


# =====================================================================
# Company resolution
# =====================================================================

@frappe.whitelist()
def get_user_permitted_company():
    """Return the company this user is permitted to access."""
    if frappe.session.user == "Administrator":
        return None

    # Super Admin sees all companies — no restriction
    if "Super Admin" in frappe.get_roles(frappe.session.user):
        return None

    # Check User Permission
    permitted = frappe.get_all(
        "User Permission",
        filters={
            "user": frappe.session.user,
            "allow": "Company",
        },
        fields=["for_value"],
        limit=1,
        ignore_permissions=True,  # needed so non-admin can call this
    )

    if permitted:
        return permitted[0].for_value

    # Fallback to User Default
    return frappe.defaults.get_user_default("company")


def set_user_company(doc, method):
    """Auto-set company on validate and before_insert."""
    if not hasattr(doc, "company"):
        return
    if frappe.session.user == "Administrator":
        return

    user_company = get_user_permitted_company()
    if not user_company:
        return

    if not doc.company:
        doc.company = user_company


# =====================================================================
# Document submission guards
# =====================================================================

def prevent_submit_for_basic(doc, method):
    """Block Company Basic users from submitting any transactional document."""
    if frappe.session.user == "Administrator":
        return

    user_roles = frappe.get_roles(frappe.session.user)

    # If user has Company Basic but no higher role, block submit
    if (
        "Company Basic" in user_roles
        and "Company Staff" not in user_roles
        and "Company Admin" not in user_roles
        and "Super Admin" not in user_roles
    ):
        frappe.throw(
            _(
                "Company Basic users can only create drafts. "
                "Please ask a Company Staff or Company Admin to submit this document."
            ),
            frappe.PermissionError,
        )


# =====================================================================
# User validation
# =====================================================================

def validate_user_role_profile(doc, method):
    """
    Enforce on every User save:
      1. Role Profile is set and is one of the four approved values.
      2. For company-scoped profiles (Company Admin / Staff / Basic),
         a company must be assigned — either via the `company` field
         or via a User Permission of type Company.
      3. Super Admin profile is exempt from the company check.
      4. Company Admin callers auto-inherit their own company.
    """
    # Skip system accounts and disabled users
    if doc.name in ("Administrator", "Guest"):
        return
    if doc.enabled == 0:
        return

    # ---- 1. Role Profile required and approved ----
    if not doc.role_profile_name:
        frappe.throw(
            _("Role Profile is required. Please select one of: {0}.").format(
                ", ".join(ALLOWED_ROLE_PROFILES)
            ),
            title=_("Role Profile Required"),
        )

    if doc.role_profile_name not in ALLOWED_ROLE_PROFILES:
        frappe.throw(
            _("Invalid Role Profile '{0}'. Allowed values are: {1}.").format(
                doc.role_profile_name, ", ".join(ALLOWED_ROLE_PROFILES)
            ),
            title=_("Invalid Role Profile"),
        )

    # ---- 2. Super Admin bypass ----
    if doc.role_profile_name == "Super Admin":
        return

    # ---- 3. Identify the caller ----
    caller = frappe.session.user
    caller_roles = frappe.get_roles(caller)

    is_admin_caller = (
        caller == "Administrator"
        or "Super Admin" in caller_roles
        or "System Manager" in caller_roles
    )
    is_company_admin_caller = "Company Admin" in caller_roles

    # ---- 4. Company Admin caller — auto-inherit their company ----
    if is_company_admin_caller and not is_admin_caller:
        caller_company = frappe.db.get_value("User", caller, "company")
        if caller_company and not doc.company:
            doc.company = caller_company
        return

    # ---- 5. Admin / Super Admin caller — company must be explicitly set ----
    if is_admin_caller and doc.role_profile_name in COMPANY_SCOPED_PROFILES:
        has_company_field = bool(doc.get("company"))
        has_user_permission = frappe.db.exists(
            "User Permission",
            {"user": doc.name, "allow": "Company"},
        )

        if not has_company_field and not has_user_permission:
            frappe.throw(
                _(
                    "Users with Role Profile '{0}' must be assigned to a Company "
                    "before saving.<br><br>"
                    "Please either:<br>"
                    "&nbsp;&nbsp;• Set the <b>Company</b> field on this user's profile, OR<br>"
                    "&nbsp;&nbsp;• Add a <b>User Permission</b> (Allow: Company, For Value: the company)<br><br>"
                    "Super Admin users are exempt — they have cross-company access by design."
                ).format(doc.role_profile_name),
                title=_("Company Assignment Required"),
            )


# =====================================================================
# Delete protection
# =====================================================================

def prevent_delete_for_staff(doc, method):
    """Prevent Company Staff from deleting any record."""
    if frappe.session.user == "Administrator":
        return

    user_roles = frappe.get_roles(frappe.session.user)
    if (
        "Company Staff" in user_roles
        and "Company Admin" not in user_roles
        and "Super Admin" not in user_roles
    ):
        frappe.throw(
            _(
                "Company Staff users are not permitted to delete records. "
                "Please contact your Company Admin."
            ),
            frappe.PermissionError,
        )