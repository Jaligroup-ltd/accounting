(function () {
    function send_ebm(frm, extra) {
        frappe.call({
            method: "jalipartners.huza_ebm.generate_ebm_invoice",
            args: Object.assign({ sales_invoice: frm.doc.name }, extra || {}),
            freeze: true,
            freeze_message: __("Sending invoice to Huza..."),
            callback: (r) => {
                if (r.message) {
                    frappe.show_alert({
                        message: __("EBM invoice {0} generated", [r.message.invoice_number]),
                        indicator: "green",
                    });
                    frm.reload_doc();
                }
            },
        });
    }

    function start_ebm(frm) {
        frappe.db
            .get_value("Customer", frm.doc.customer, ["customer_type", "tax_id", "mobile_no"])
            .then(({ message }) => {
                message = message || {};
                const is_company = message.customer_type === "Company";
                const phone = frm.doc.contact_mobile || message.mobile_no || "";

                // Individuals with a phone number on file: no dialog, just a confirmation
                if (!is_company && phone) {
                    frappe.confirm(
                        __("Send this invoice to Huza and generate the EBM invoice? This cannot be undone."),
                        () => send_ebm(frm)
                    );
                    return;
                }

                const fields = [];
                if (is_company) {
                    fields.push(
                        {
                            fieldname: "customer_tin",
                            fieldtype: "Data",
                            label: __("Customer TIN"),
                            reqd: 1,
                            default: (message.tax_id || "").replace(/\D/g, ""),
                        },
                        {
                            fieldname: "purchase_code",
                            fieldtype: "Data",
                            label: __("Purchase Code"),
                            reqd: 1,
                            default: frm.doc.po_no || "",
                            description: __("Must be different from 000000 for company customers"),
                        }
                    );
                }
                // Huza requires a phone number, so ask for it whenever none is on file
                fields.push({
                    fieldname: "customer_phone",
                    fieldtype: "Data",
                    label: __("Customer Phone"),
                    reqd: 1,
                    default: phone,
                    description: __("Example: +250788123456"),
                });

                const d = new frappe.ui.Dialog({
                    title: __("Generate EBM Invoice"),
                    fields: fields,
                    primary_action_label: __("Generate"),
                    primary_action(values) {
                        const args = { customer_phone: (values.customer_phone || "").trim() };
                        if (args.customer_phone.replace(/\D/g, "").length < 9) {
                            frappe.msgprint(__("Enter a valid phone number."));
                            return;
                        }
                        if (is_company) {
                            const tin = (values.customer_tin || "").replace(/\D/g, "");
                            const code = (values.purchase_code || "").trim();
                            if (tin.length !== 9) {
                                frappe.msgprint(__("The TIN must be 9 digits."));
                                return;
                            }
                            if (!code || code === "000000") {
                                frappe.msgprint(__("Enter a purchase code different from 000000."));
                                return;
                            }
                            args.customer_tin = tin;
                            args.purchase_code = code;
                        }
                        d.hide();
                        send_ebm(frm, args);
                    },
                });
                d.show();
            });
    }

    frappe.ui.form.on("Sales Invoice", {
        refresh(frm) {
            if (frm.is_new() || frm.doc.docstatus !== 1 || frm.doc.is_return) return;

            if (frm.doc.custom_ebm_invoice_number) {
                frm.set_intro(
                    __("EBM invoice no. {0} has been issued for this invoice", [
                        frm.doc.custom_ebm_invoice_number,
                    ]),
                    "green"
                );
                return;
            }

            const label = __("Generate EBM Invoice");
            const menu = frm.page.menu;
            const find_node = () => {
                const $a = menu.find(".dropdown-item").filter((_, e) => $(e).text().trim() === label);
                return $a.parent().is(menu) ? $a : $a.parent();
            };

            find_node().remove(); // avoid duplicates on re-render
            frm.page.add_menu_item(label, () => start_ebm(frm));
            menu.prepend(find_node()); // move to the top of the menu
        },
    });
})();