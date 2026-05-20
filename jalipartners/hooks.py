app_name = "jalipartners"
app_title = "Jalipartners App"
app_publisher = "Jali Group"
app_description = "accounting firm"
app_email = "desire.mukunzi@jaligroup.rw"
app_license = "mit"
app_include_js = [
    "/assets/jalipartners/js/company_restriction.js"
]
override_whitelisted_methods = {
    "erpnext.setup.utils.get_exchange_rate": "jalipartners.currency.get_exchange_rate"
}
doc_events = {
    "*": {
        "validate": "jalipartners.utils.set_user_company",
        "before_insert": "jalipartners.utils.set_user_company",
    }
}
# Custom Login and splash logo (fallback values — used only when DB fields are empty)
app_logo_url = "/assets/jalipartners/images/jali_partners_transparent.png"

# Optional: also override the login page splash
splash_image = "/assets/jalipartners/images/jali_partners_transparent.png"

# Optional: browser tab favicon
website_context = {
    "favicon": "/assets/jalipartners/images/jali_partners_transparent.png",
    "splash_image": "/assets/jalipartners/images/jali_partners_transparent.png",
}

# Re-assert branding on every `bench migrate` to prevent ERPNext defaults
# from winning the hook-fallback race when DB fields are empty.
before_migrate = "jalipartners.branding.apply_branding"