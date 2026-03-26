$(document).ready(function () {

    const SKIP_DOCTYPES = [
        "User", "Role", "Company", "Currency", "Currency Exchange",
        "System Settings", "Global Defaults", "DefaultValue"
    ];

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

    function apply_css() {
        if (document.getElementById("company-field-css")) return;
        const style = document.createElement("style");
        style.id = "company-field-css";
        style.innerHTML = `[data-fieldname="company"] { display: none !important; }`;
        document.head.appendChild(style);
    }

    function apply_company_to_form(frm, user_company) {
        if (!frm?.doctype) return;
        if (SKIP_DOCTYPES.includes(frm.doctype)) return;
        if (!frm.fields_dict?.company) return;

        // Set synchronously first
        frm.doc.company = user_company;

        // Then trigger dependent fields
        frm.set_value("company", user_company)
            .then(() => {
                frm.set_df_property("company", "hidden", 1);
                frm.refresh_field("company");
            })
            .catch(() => {
                frm.set_df_property("company", "hidden", 1);
                frm.refresh_field("company");
            });
    }

    function get_company_then_apply() {
        // Call our custom whitelisted Python method
        frappe.call({
            method: "jalipartners.utils.get_user_permitted_company",
            callback: function (r) {
                const user_company = r?.message;

                if (!user_company) {
                    console.warn("[Jali] No company found for:", frappe.session.user);
                    return;
                }

                console.log("[Jali] Company found:", user_company);

                // Cache in boot for this session
                frappe.boot.user = frappe.boot.user || {};
                frappe.boot.user.defaults = frappe.boot.user.defaults || {};
                frappe.boot.user.defaults.company = user_company;

                if (frappe.defaults.set_user_default_local) {
                    frappe.defaults.set_user_default_local("company", user_company);
                }

                // Apply CSS hide
                apply_css();

                // Apply to any currently open form
                if (cur_frm) {
                    apply_company_to_form(cur_frm, user_company);
                }

                // Patch frappe.ui.Form for all future forms
                let attempts = 0;
                const interval = setInterval(function () {
                    attempts++;
                    if (attempts > 100) {
                        clearInterval(interval);
                        return;
                    }
                    if (!frappe.ui?.Form?.prototype) return;

                    clearInterval(interval);

                    const _orig_setup = frappe.ui.Form.prototype.setup;
                    frappe.ui.Form.prototype.setup = function () {
                        if (this.doc && !SKIP_DOCTYPES.includes(this.doctype)) {
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
            }
        });
    }

    // Entry point
    wait_for_frappe(function () {
        if (frappe.session.user === "Administrator") return;
        get_company_then_apply();
    });

});