import json

import frappe
from frappe.permissions import setup_custom_perms

ALLOWED_ROLE_PROFILES = [
	"Super Admin",
	"Super Staff",
	"Company Admin",
	"Company Staff",
	"Company Basic",
	"Credentials Feeder",
]

SUPER_STAFF_ROLE = "Super Staff"
SUPER_STAFF_SOURCE_ROLE = "Company Staff"
SUPER_STAFF_PERMS = [
	"read",
	"write",
	"create",
	"submit",
	"cancel",
	"amend",
	"delete",
	"report",
	"export",
	"import",
	"print",
	"email",
	"share",
	"select",
]
# Always forced off for Super Staff, whatever the source roles allow
SUPER_STAFF_DENIED_PERMS = {"delete", "cancel", "amend"}
# Admin-type doctypes Super Staff must never get permissions on
SUPER_STAFF_BLOCKED_DOCTYPES = {
	"User",
	"Role",
	"User Permission",
	"Role Permission for Page and Report",
	"DocPerm",
	"Custom DocPerm",
	"Has Role",
	"Role Profile",
	"Module Profile",
	"Server Script",
	"Custom Field",
	"Property Setter",
	"Customize Form",
	"System Settings",
	"Bank Credential",
	"Deleted Document",
}
# Global settings doctypes Super Staff may read but never change
SUPER_STAFF_SETTINGS_READ_ONLY = {
	"Accounts Settings",
	"Selling Settings",
	"Buying Settings",
	"Stock Settings",
	"Global Defaults",
}
# Roles whose permissions must never be inherited by Super Staff
SUPER_STAFF_NEVER_INHERIT = {"System Manager", "Administrator", "All", "Guest"}


def setup_user_role_profile_restrictions():
	"""
	Apply Property Setters on the User doctype:
	  1. Role Profile field becomes mandatory
	  2. Role Profile dropdown filtered to the approved profiles only

	Also provisions the Super Staff role, its permissions and its Role Profile.

	Idempotent, safe to run repeatedly via after_migrate hook.
	"""

	# Super Staff role, permissions and role profile (must exist before users pick it)
	setup_super_staff()
	setup_super_staff_role_profile()

	# 1. Mandatory flag
	_set_property(
		doctype="User", fieldname="role_profile_name", property_name="reqd", value="1", property_type="Check"
	)

	# 2. Link filter for dropdown
	link_filter_value = json.dumps([["Role Profile", "name", "in", ALLOWED_ROLE_PROFILES]])
	_set_property(
		doctype="User",
		fieldname="role_profile_name",
		property_name="link_filters",
		value=link_filter_value,
		property_type="JSON",
	)

	frappe.db.commit()
	print("✓ User Role Profile restrictions applied")


def _super_staff_source_roles():
	"""Company Staff role plus every role in the Company Staff Role Profile."""
	roles = {SUPER_STAFF_SOURCE_ROLE}
	if frappe.db.exists("Role Profile", SUPER_STAFF_SOURCE_ROLE):
		profile = frappe.get_doc("Role Profile", SUPER_STAFF_SOURCE_ROLE)
		roles.update(r.role for r in profile.roles)
	return roles - SUPER_STAFF_NEVER_INHERIT - {SUPER_STAFF_ROLE}


def _merged_source_perms(roles):
	"""OR the permlevel 0 permissions of all source roles, per doctype."""
	# Frappe ignores standard DocPerm for a doctype once it has any Custom DocPerm
	custom_parents = set(frappe.get_all("Custom DocPerm", pluck="parent"))

	rows = []
	for perm_doctype in ("Custom DocPerm", "DocPerm"):
		for r in frappe.get_all(
			perm_doctype,
			filters={"role": ["in", list(roles)], "permlevel": 0},
			fields=["parent", "if_owner", *SUPER_STAFF_PERMS],
		):
			if perm_doctype == "DocPerm" and r.parent in custom_parents:
				continue
			rows.append(r)

	merged = {}
	for r in rows:
		m = merged.setdefault(r.parent, {**{p: 0 for p in SUPER_STAFF_PERMS}, "if_owner": 1})
		for p in SUPER_STAFF_PERMS:
			m[p] = 1 if (m[p] or r.get(p)) else 0
		# Own-documents-only survives only if every contributing row has it
		m["if_owner"] = 1 if (m["if_owner"] and r.get("if_owner")) else 0
	return merged


def _upsert_super_staff_perm(doctype, values):
	"""
	Create or update the Super Staff permission row for one doctype.
	Returns True if anything changed. Writes directly (no per-property
	validation) because the values come from already-valid permission rows.
	"""
	# Copies the standard DocPerm rows into Custom DocPerm once; no-op afterwards
	setup_custom_perms(doctype)

	name = frappe.db.get_value(
		"Custom DocPerm", {"parent": doctype, "role": SUPER_STAFF_ROLE, "permlevel": 0}
	)

	if name:
		current = frappe.db.get_value("Custom DocPerm", name, list(values), as_dict=True)
		if all(int(current.get(k) or 0) == int(v) for k, v in values.items()):
			return False
		frappe.db.set_value("Custom DocPerm", name, values)
		return True

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": SUPER_STAFF_ROLE,
			"permlevel": 0,
			**values,
		}
	).insert(ignore_permissions=True)
	return True


def setup_super_staff():
	"""
	Create the Super Staff role and give it the merged permissions of the
	Company Staff profile, with delete, cancel and amend forced off. Idempotent.
	"""
	if not frappe.db.exists("Role", SUPER_STAFF_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": SUPER_STAFF_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
		print(f"  Created Role: {SUPER_STAFF_ROLE}")

	merged = _merged_source_perms(_super_staff_source_roles())
	targets = {
		doctype: src
		for doctype, src in merged.items()
		if doctype not in SUPER_STAFF_BLOCKED_DOCTYPES and frappe.db.exists("DocType", doctype)
	}

	changed = 0
	for i, (doctype, src) in enumerate(sorted(targets.items()), start=1):
		values = {}
		for ptype in SUPER_STAFF_PERMS:
			if ptype in SUPER_STAFF_DENIED_PERMS:
				values[ptype] = 0
			elif doctype in SUPER_STAFF_SETTINGS_READ_ONLY and ptype != "read":
				values[ptype] = 0
			else:
				values[ptype] = src[ptype]
		values["if_owner"] = src["if_owner"]

		if _upsert_super_staff_perm(doctype, values):
			changed += 1
		if i % 50 == 0:
			print(f"  Super Staff permissions: {i}/{len(targets)} doctypes processed")

	frappe.clear_cache()
	print(f"  Super Staff permissions synced ({changed} of {len(targets)} doctypes changed)")


def setup_super_staff_role_profile():
	"""Create the Super Staff Role Profile (the Super Staff role only). Idempotent."""
	if frappe.db.exists("Role Profile", SUPER_STAFF_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role Profile",
			"role_profile": SUPER_STAFF_ROLE,
			"roles": [{"role": SUPER_STAFF_ROLE}],
		}
	).insert(ignore_permissions=True)
	print(f"  Created Role Profile: {SUPER_STAFF_ROLE}")


def _set_property(doctype, fieldname, property_name, value, property_type):
	"""Create or update a Property Setter idempotently."""

	existing = frappe.db.get_value(
		"Property Setter", {"doc_type": doctype, "field_name": fieldname, "property": property_name}, "name"
	)

	if existing:
		# Update if value changed
		current_value = frappe.db.get_value("Property Setter", existing, "value")
		if current_value != value:
			frappe.db.set_value("Property Setter", existing, "value", value)
			print(f"  Updated Property Setter: {doctype}.{fieldname}.{property_name}")
	else:
		# Create new
		ps = frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": doctype,
				"field_name": fieldname,
				"property": property_name,
				"value": value,
				"property_type": property_type,
			}
		)
		ps.insert(ignore_permissions=True)
		print(f"  Created Property Setter: {doctype}.{fieldname}.{property_name}")