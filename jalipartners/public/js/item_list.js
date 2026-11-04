// "Sync from Huza" entry in the Item list Menu (first position)
(function () {
    const settings = frappe.listview_settings["Item"] || {};
    const original_onload = settings.onload;

    settings.onload = function (listview) {
        // keep ERPNext's own Item list behaviour
        if (original_onload) original_onload.call(this, listview);

        const label = __("Sync from Huza");

        listview.page.add_menu_item(label, () => {
            frappe.confirm(
                __("Fetch items from Huza and create or update them in ERPNext?"),
                () => {
                    frappe.call({
                        method: "jalipartners.huza_sync.sync_items_from_huza",
                        freeze: true,
                        freeze_message: __("Queuing Huza sync..."),
                        callback: () => {
                            frappe.show_alert({
                                message: __("Sync started in the background. You will be notified when it finishes."),
                                indicator: "blue",
                            });
                        },
                    });
                }
            );
        });

        // add_menu_item appends, so move our entry to the top of the menu
        const menu = listview.page.menu;
        const $a = menu
            .find(".dropdown-item")
            .filter((_, e) => $(e).text().trim() === label);
        const $node = $a.parent().is(menu) ? $a : $a.parent();
        menu.prepend($node);

        // result notification from the background job
        frappe.realtime.off("huza_item_sync_done");
        frappe.realtime.on("huza_item_sync_done", (r) => {
            let msg = r.aborted
                ? __("Huza sync aborted. Check the Error Log.")
                : __("Created: {0}, Updated: {1}, Failed: {2}", [r.created, r.updated, r.failed]);

            if (r.missing_tax_templates && r.missing_tax_templates.length) {
                msg +=
                    "<br><br>" +
                    __("No Item Tax Template with a title starting with the code, for tax codes: {0}", [
                        r.missing_tax_templates.join(", "),
                    ]);
            }
            if (r.failed) {
                msg += "<br><br>" + __("See Error Log for the failed items.");
            }

            frappe.msgprint({
                title: __("Huza Sync"),
                message: msg,
                indicator:
                    r.failed || r.aborted || (r.missing_tax_templates || []).length
                        ? "orange"
                        : "green",
            });
            listview.refresh();
        });
    };

    frappe.listview_settings["Item"] = settings;
})();