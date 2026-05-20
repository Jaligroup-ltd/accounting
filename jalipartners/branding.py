import frappe

BRANDING_LOGO = "/assets/jalipartners/images/jali_partners_transparent.png"


def apply_branding():
    """Ensure Website Settings and Navbar Settings always point to the Jali logo.

    Runs automatically on `bench migrate`. The hook fallbacks in hooks.py are
    only used when these DB fields are empty, and ERPNext's hooks can win the
    fallback race — so we set the DB values explicitly here.
    """
    frappe.db.set_value("Website Settings", "Website Settings", {
        "favicon": BRANDING_LOGO,
        "splash_image": BRANDING_LOGO,
    })
    frappe.db.set_value("Navbar Settings", "Navbar Settings", {
        "app_logo": BRANDING_LOGO,
    })
    frappe.db.commit()
    print(f"✓ Branding re-applied: {BRANDING_LOGO}")