(function () {
    function show_notification_results(r) {
        const n = r.notifications || {};
        const lines = [];
        let failed = false;
        [["sms", __("SMS")], ["email", __("Email")]].forEach(([key, label]) => {
            const s = n[key];
            if (!s) return;
            if (s.ok) {
                lines.push(__("{0}: sent", [label]));
            } else {
                failed = true;
                lines.push(
                    __("{0}: failed ({1})", [label, frappe.utils.escape_html(s.error || __("unknown error"))])
                );
            }
        });
        if (!lines.length) return;
        if (failed) {
            lines.push("<br>" + __("The EBM invoice itself was generated successfully."));
        }
        frappe.msgprint({
            title: __("EBM invoice {0}", [r.invoice_number]),
            message: lines.join("<br>"),
            indicator: failed ? "orange" : "green",
        });
    }

    function send_ebm(frm, extra) {
        frappe.call({
            method: "jalipartners.huza_ebm.generate_ebm_invoice",
            args: Object.assign({ sales_invoice: frm.doc.name }, extra || {}),
            freeze: true,
            freeze_message: __("Sending invoice to Huza..."),
            callback: (r) => {
                if (!r.message) return;
                frappe.show_alert({
                    message: __("EBM invoice {0} generated", [r.message.invoice_number]),
                    indicator: "green",
                });
                show_notification_results(r.message);
                frm.reload_doc();
            },
        });
    }

    function start_ebm(frm) {
        frappe.db
            .get_value("Customer", frm.doc.customer, ["customer_type", "tax_id", "mobile_no", "email_id"])
            .then(({ message }) => {
                message = message || {};
                const is_company = message.customer_type === "Company";
                const phone = frm.doc.contact_mobile || message.mobile_no || "";
                const email = frm.doc.contact_email || message.email_id || "";

                const fields = [
                    {
                        fieldtype: "HTML",
                        options:
                            "<p class='text-muted'>" +
                            __("This sends the invoice to Huza to generate the EBM invoice. It cannot be undone.") +
                            "</p>",
                    },
                ];

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

                fields.push(
                    {
                        fieldname: "customer_phone",
                        fieldtype: "Data",
                        label: __("Customer Phone"),
                        reqd: 1,
                        default: phone,
                        description: __("Example: +250788123456"),
                    },
                    {
                        fieldname: "customer_email",
                        fieldtype: "Data",
                        options: "Email",
                        label: __("Customer Email"),
                        default: email,
                        mandatory_depends_on: "eval:doc.send_email",
                    },
                    { fieldtype: "Section Break", label: __("Send invoice to the customer") },
                    {
                        fieldname: "send_sms",
                        fieldtype: "Check",
                        label: __("Send by SMS"),
                        default: 0,
                        // description: __("Uses SMS credits"),
                    },
                    { fieldtype: "Column Break" },
                    {
                        fieldname: "send_email",
                        fieldtype: "Check",
                        label: __("Send by email"),
                        default: 0,
                    }
                );

                const d = new frappe.ui.Dialog({
                    title: __("Generate EBM Invoice"),
                    fields: fields,
                    primary_action_label: __("Generate"),
                    primary_action(values) {
                        const phone_value = (values.customer_phone || "").trim();
                        if (phone_value.replace(/\D/g, "").length < 9) {
                            frappe.msgprint(__("Enter a valid phone number."));
                            return;
                        }
                        const email_value = (values.customer_email || "").trim();
                        if (values.send_email && !email_value) {
                            frappe.msgprint(__("Enter the customer email to send the invoice by email."));
                            return;
                        }

                        const args = {
                            customer_phone: phone_value,
                            customer_email: email_value,
                            send_sms: values.send_sms ? 1 : 0,
                            send_email: values.send_email ? 1 : 0,
                        };

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