import frappe


ALLOWED_ROLE_PROFILES = ["Super Admin", "Company Admin", "Company Staff", "Company Basic"]


def setup_user_role_profile_restrictions():
    """
    Apply Property Setters on the User doctype:
      1. Role Profile field becomes mandatory
      2. Role Profile dropdown filtered to the four approved profiles only
    
    Idempotent — safe to run repeatedly via after_migrate hook.
    """
    
    # 1. Mandatory flag
    _set_property(
        doctype="User",
        fieldname="role_profile_name",
        property_name="reqd",
        value="1",
        property_type="Check"
    )
    
    # 2. Link filter for dropdown
    import json
    link_filter_value = json.dumps([
        ["Role Profile", "name", "in", ALLOWED_ROLE_PROFILES]
    ])
    _set_property(
        doctype="User",
        fieldname="role_profile_name",
        property_name="link_filters",
        value=link_filter_value,
        property_type="JSON"
    )
    
    frappe.db.commit()
    print("✓ User Role Profile restrictions applied")


def _set_property(doctype, fieldname, property_name, value, property_type):
    """Create or update a Property Setter idempotently."""
    
    existing = frappe.db.get_value("Property Setter", {
        "doc_type": doctype,
        "field_name": fieldname,
        "property": property_name
    }, "name")
    
    if existing:
        # Update if value changed
        current_value = frappe.db.get_value("Property Setter", existing, "value")
        if current_value != value:
            frappe.db.set_value("Property Setter", existing, "value", value)
            print(f"  Updated Property Setter: {doctype}.{fieldname}.{property_name}")
    else:
        # Create new
        ps = frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": doctype,
            "field_name": fieldname,
            "property": property_name,
            "value": value,
            "property_type": property_type
        })
        ps.insert(ignore_permissions=True)
        print(f"  Created Property Setter: {doctype}.{fieldname}.{property_name}")