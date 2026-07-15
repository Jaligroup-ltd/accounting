app_name = "jalipartners"
app_title = "Jalipartners App"
app_publisher = "Jali Group"
app_description = "accounting firm"
app_email = "desire.mukunzi@jaligroup.rw"
app_license = "mit"
app_include_js = ["/assets/jalipartners/js/company_restriction.js"]
override_whitelisted_methods = {
	"erpnext.setup.utils.get_exchange_rate": "jalipartners.currency.get_exchange_rate"
}
doc_events = {
	"*": {
		"validate": "jalipartners.utils.set_user_company",
		"before_insert": "jalipartners.utils.set_user_company",
	},
	"Sales Invoice": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
	"Purchase Invoice": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
	"Payment Entry": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
	"Journal Entry": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
	"Delivery Note": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
	"Sales Order": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
	"Purchase Order": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
	"Stock Entry": {"before_submit": "jalipartners.utils.prevent_submit_for_basic"},
}

# Custom Login and splash logo (fallback values — used only when DB fields are empty)
app_logo_url = "/assets/jalipartners/images/jali_partners_transparent.png"

# Optional: also override the login page splash
splash_image = "/assets/jalipartners/images/jali_partners_transparent.png"

# Optional: browser tab favicon
website_context = {
	"favicon": "/assets/jalipartners/images/jali_partners_transparent.png",
	"splash_image": "/assets/jalipartners/images/jali_partners_transparent.png",
	"footer_powered": '<a href="https://jalipartners.com">Powered by Jalipartners</a>',
	"hide_footer_signup": True,
}

# Re-assert branding on every `bench migrate` to prevent ERPNext defaults
# from winning the hook-fallback race when DB fields are empty.
before_migrate = "jalipartners.branding.apply_branding"
dashboard_chart_source = "jalipartners.jalipartners.api.dashboard"
after_migrate = [
	"jalipartners.setup.user_customization.setup_user_role_profile_restrictions",
]
