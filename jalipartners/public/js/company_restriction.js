/**
 * company_restriction.js
 *
 * Defaults the Company field to the logged-in user's permitted company and
 * hides it, so ordinary users never pick a company by hand.
 *
 * Scoping rules (why this file is not a simple global patch):
 *
 *   1. Some doctypes choose their company deliberately - Bank Credential holds
 *      one company's bank logins, and forcing the user's own company would make
 *      a second company's record impossible to create. Those live in
 *      SKIP_DOCTYPES and are left completely alone.
 *
 *   2. The CSS that hides the field is scoped to a body class that is toggled
 *      per route. An unscoped `[data-fieldname="company"] { display: none }`
 *      rule hides the field on skipped doctypes too, which is what broke
 *      Bank Credential and Bank Feed.
 *
 *   3. The company is only defaulted on NEW documents. Writing
 *      `frm.doc.company = user_company` on an already-saved document silently
 *      rewrites another company's record the next time it is saved. Existing
 *      values are never touched.
 */

$(document).ready(function () {
	// Doctypes where the user must be free to choose the company, or where a
	// company makes no sense. Add a doctype here when its company is data
	// rather than a default.
	const SKIP_DOCTYPES = [
		// configuration / global
		"User",
		"Role",
		"Company",
		"Currency",
		"Currency Exchange",
		"System Settings",
		"Global Defaults",
		"DefaultValue",
		// company is chosen per record, not inherited from the user
		"Bank Credential",
		"Bank Feed",
		"Company Bank Credential",
	];

	const BODY_CLASS = "jali-hide-company";

	function is_restricted(doctype) {
		return Boolean(doctype) && !SKIP_DOCTYPES.includes(doctype);
	}

	function wait_for_frappe(callback) {
		let attempts = 0;
		const interval = setInterval(function () {
			attempts++;
			if (attempts > 200) {
				clearInterval(interval);
				return;
			}
			if (frappe?.session?.user && frappe.session.user !== "Guest") {
				clearInterval(interval);
				callback();
			}
		}, 50);
	}

	/* ------------------------------------------------------------------ *
	 * CSS: injected once, but only active while the body class is set.
	 * ------------------------------------------------------------------ */

	function apply_css() {
		if (document.getElementById("company-field-css")) return;
		const style = document.createElement("style");
		style.id = "company-field-css";
		style.innerHTML =
			`body.${BODY_CLASS} [data-fieldname="company"] { display: none !important; }`;
		document.head.appendChild(style);
	}

	function sync_company_css() {
		// route looks like ["Form", "Sales Invoice", "SINV-0001"] or
		// ["List", "Sales Invoice", "List"]
		const route = frappe.get_route ? frappe.get_route() : [];
		const doctype = route && route.length > 1 ? route[1] : null;
		document.body.classList.toggle(BODY_CLASS, is_restricted(doctype));
	}

	/* ------------------------------------------------------------------ *
	 * Form handling
	 * ------------------------------------------------------------------ */

	function apply_company_to_form(frm, user_company) {
		if (!frm?.doctype) return;
		if (!is_restricted(frm.doctype)) return;
		if (!frm.fields_dict?.company) return;

		// Never overwrite a saved document's company. Doing so rewrites another
		// company's record on the next save, with no visible sign.
		const is_new = typeof frm.is_new === "function" ? frm.is_new() : !frm.doc?.name;
		if (!is_new) {
			frm.set_df_property("company", "hidden", 1);
			return;
		}

		if (!frm.doc.company) {
			frm.doc.company = user_company;
			frm.set_value("company", user_company)
				.then(() => {
					frm.set_df_property("company", "hidden", 1);
					frm.refresh_field("company");
				})
				.catch(() => {
					frm.set_df_property("company", "hidden", 1);
					frm.refresh_field("company");
				});
		} else {
			frm.set_df_property("company", "hidden", 1);
		}
	}

	function get_company_then_apply() {
		frappe.call({
			method: "jalipartners.utils.get_user_permitted_company",
			callback: function (r) {
				const user_company = r?.message;

				if (!user_company) {
					console.warn("[Jali] No company found for:", frappe.session.user);
					return;
				}

				console.log("[Jali] Company found:", user_company);

				frappe.boot.user = frappe.boot.user || {};
				frappe.boot.user.defaults = frappe.boot.user.defaults || {};
				frappe.boot.user.defaults.company = user_company;

				if (frappe.defaults.set_user_default_local) {
					frappe.defaults.set_user_default_local("company", user_company);
				}

				apply_css();
				sync_company_css();

				// Keep the body class in step with the current route, so the
				// rule stops applying the moment the user opens a skipped
				// doctype.
				if (frappe.router?.on) {
					frappe.router.on("change", sync_company_css);
				} else {
					$(document).on("page-change", sync_company_css);
				}

				if (cur_frm) {
					apply_company_to_form(cur_frm, user_company);
				}

				let attempts = 0;
				const interval = setInterval(function () {
					attempts++;
					if (attempts > 100) {
						clearInterval(interval);
						return;
					}
					if (!frappe.ui?.Form?.prototype) return;

					clearInterval(interval);

					// setup(): seed the default on new docs only. The original
					// version set this on every form, saved records included.
					const _orig_setup = frappe.ui.Form.prototype.setup;
					frappe.ui.Form.prototype.setup = function () {
						if (this.doc && is_restricted(this.doctype) && !this.doc.company) {
							this.doc.company = user_company;
						}
						_orig_setup?.apply(this, arguments);
					};

					const _orig_onload = frappe.ui.Form.prototype.onload;
					frappe.ui.Form.prototype.onload = function () {
						_orig_onload?.apply(this, arguments);
						apply_company_to_form(this, user_company);
					};

					const _orig_refresh = frappe.ui.Form.prototype.refresh;
					frappe.ui.Form.prototype.refresh = function () {
						_orig_refresh?.apply(this, arguments);
						apply_company_to_form(this, user_company);
					};

					console.log("[Jali] Form prototype patched for:", user_company);
				}, 50);
			},
		});
	}

	wait_for_frappe(function () {
		if (frappe.session.user === "Administrator") return;
		get_company_then_apply();
	});
});