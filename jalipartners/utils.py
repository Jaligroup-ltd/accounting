import frappe
from frappe import _

SUPER_STAFF_ROLE = "Super Staff"
SUPER_STAFF_OVERRIDE_ROLES = {"System Manager", "Super Admin", "Company Admin"}

# Housekeeping doctypes that normal use deletes as a side effect (own comments, todos, etc.)
SUPER_STAFF_DELETE_EXEMPT = {
	"ToDo",
	"Comment",
	"Notification Log",
	"Route History",
	"Access Log",
	"Energy Point Log",
	"Prepared Report",
}


@frappe.whitelist()
def get_user_permitted_company():
	"""Return the company this user is permitted to access"""
	if frappe.session.user == "Administrator":
		return None

	roles = frappe.get_roles(frappe.session.user)

	# Super Admin and Super Staff see all companies, no restriction
	if "Super Admin" in roles or SUPER_STAFF_ROLE in roles:
		return None

	# Check User Permission
	permitted = frappe.get_all(
		"User Permission",
		filters={"user": frappe.session.user, "allow": "Company"},
		fields=["for_value"],
		limit=1,
		ignore_permissions=True,  # needed so non-admin can call this
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


def prevent_submit_for_basic(doc, method):
	"""Block Company Basic users from submitting any transactional document"""
	if frappe.session.user == "Administrator":
		return

	user_roles = frappe.get_roles(frappe.session.user)

	# If user has Company Basic but no higher role, block submit
	if (
		"Company Basic" in user_roles
		and "Company Staff" not in user_roles
		and "Company Admin" not in user_roles
		and "Super Admin" not in user_roles
		and "Credentials Feeder" not in user_roles
	):
		frappe.throw(
			_(
				"Company Basic users can only create drafts. "
				"Please ask a Company Staff or Company Admin to submit this document."
			),
			frappe.PermissionError,
		)


def _is_restricted_super_staff():
	"""True when the user is Super Staff with no role that overrides the restriction."""
	if frappe.session.user == "Administrator":
		return False
	roles = set(frappe.get_roles(frappe.session.user))
	return SUPER_STAFF_ROLE in roles and not (SUPER_STAFF_OVERRIDE_ROLES & roles)


def block_super_staff_delete(doc, method=None):
	"""Server-side backstop: Super Staff can never delete records."""
	if doc.doctype in SUPER_STAFF_DELETE_EXEMPT:
		return
	if _is_restricted_super_staff():
		frappe.throw(_("Super Staff users cannot delete records."), frappe.PermissionError)


def block_super_staff_cancel(doc, method=None):
	"""Server-side backstop: Super Staff can never cancel submitted documents."""
	if _is_restricted_super_staff():
		frappe.throw(
			_("Super Staff users cannot cancel submitted documents."), frappe.PermissionError
		)