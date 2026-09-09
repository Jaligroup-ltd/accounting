frappe.ui.form.on("Bank Reconciliation Tool", {
	refresh(frm) {
		// Custom buttons are cleared on every refresh, so no duplicate guard needed.
		frm.add_custom_button(__("Cash Coding"), () => {
			if (!frm.doc.bank_account || !frm.doc.bank_statement_to_date) {
				frappe.msgprint(__("Select a bank account and statement dates first"));
				return;
			}
			new CashCoding(frm);
		});
	},
});

class CashCoding {
	constructor(frm) {
		this.frm = frm;
		this.rows = [];
		this.make_dialog();
		this.dialog.show();
		this.load_rows();
	}

	make_dialog() {
		this.dialog = new frappe.ui.Dialog({
			title: __("Cash Coding"),
			size: "extra-large",
			fields: [
				{
					fieldtype: "Data",
					fieldname: "search",
					label: __("Filter description"),
					description: __("e.g. CHARGE, COMMISSION, INTEREST"),
					change: frappe.utils.debounce(() => this.load_rows(), 400),
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Link",
					fieldname: "account",
					label: __("Code to Account"),
					options: "Account",
					reqd: 1,
					get_query: () => ({
						filters: {
							company: this.frm.doc.company,
							is_group: 0,
							root_type: ["in", ["Expense", "Income"]],
							account_type: ["not in", ["Receivable", "Payable"]],
						},
					}),
					change: () => this.update_primary(),
				},
				{ fieldtype: "Section Break" },
				{ fieldtype: "HTML", fieldname: "rows" },
			],
			primary_action_label: __("Code Selected"),
			primary_action: () => this.submit(),
		});
	}

	load_rows() {
		const $host = this.dialog.fields_dict.rows.$wrapper;
		$host.html(`<div class="text-muted">${__("Loading...")}</div>`);

		frappe.call({
			method: "jalipartners.cash_coding.get_uncoded_transactions",
			args: {
				bank_account: this.frm.doc.bank_account,
				from_date: this.frm.doc.bank_statement_from_date,
				to_date: this.frm.doc.bank_statement_to_date,
				search: this.dialog.get_value("search"),
			},
			callback: (r) => {
				this.rows = r.message || [];
				this.render();
			},
		});
	}

	render() {
		const $host = this.dialog.fields_dict.rows.$wrapper;

		if (!this.rows.length) {
			$host.html(
				`<div class="text-muted">${__("No unreconciled transactions match")}</div>`
			);
			this.update_primary();
			return;
		}

		const body = this.rows
			.map((t) => {
				const amount = format_currency(t.unallocated_amount, t.currency);
				const direction = t.deposit > 0 ? "text-success" : "text-danger";
				return `
					<tr>
						<td><input type="checkbox" class="cc-row"
							data-name="${frappe.utils.escape_html(t.name)}"></td>
						<td class="text-muted">${frappe.datetime.str_to_user(t.date)}</td>
						<td>${frappe.utils.escape_html(t.description || "")}</td>
						<td class="text-right ${direction}">${amount}</td>
					</tr>`;
			})
			.join("");

		$host.html(`
			<div style="max-height:420px; overflow:auto; border:1px solid var(--border-color)">
				<table class="table table-hover" style="margin-bottom:0">
					<thead style="position:sticky; top:0; background:var(--fg-color)">
						<tr>
							<th style="width:40px"><input type="checkbox" class="cc-all"></th>
							<th style="width:110px">${__("Date")}</th>
							<th>${__("Description")}</th>
							<th class="text-right" style="width:150px">${__("Amount")}</th>
						</tr>
					</thead>
					<tbody>${body}</tbody>
				</table>
			</div>
			<div class="cc-count text-muted" style="margin-top:8px"></div>
		`);

		// Header checkbox drives all visible rows.
		$host.find(".cc-all").on("change", (e) => {
			$host.find(".cc-row").prop("checked", e.currentTarget.checked);
			this.update_primary();
		});

		$host.find(".cc-row").on("change", () => {
			const total = $host.find(".cc-row").length;
			const checked = $host.find(".cc-row:checked").length;
			const $all = $host.find(".cc-all");
			$all.prop("checked", checked === total);
			$all.prop("indeterminate", checked > 0 && checked < total);
			this.update_primary();
		});

		this.update_primary();
	}

	get_selected() {
		return this.dialog.$wrapper
			.find(".cc-row:checked")
			.map((_i, el) => $(el).data("name"))
			.get();
	}

	update_primary() {
		const selected = this.get_selected();
		const account = this.dialog.get_value("account");

		this.dialog.$wrapper
			.find(".cc-count")
			.text(selected.length ? __("{0} selected", [selected.length]) : "");

		this.dialog.get_primary_btn().prop("disabled", !selected.length || !account);
	}

	submit() {
		const selected = this.get_selected();
		const account = this.dialog.get_value("account");

		frappe.confirm(
			__("Code {0} transactions to {1}?", [selected.length, account]),
			() => {
				frappe.call({
					method: "jalipartners.cash_coding.bulk_cash_code",
					args: { transactions: selected, account: account },
					freeze: true,
					freeze_message: __("Coding {0} transactions...", [selected.length]),
					callback: (r) => {
						const res = r.message || {};

						if (res.queued) {
							frappe.show_alert({
								message: __("Queued {0} transactions", [res.count]),
								indicator: "blue",
							});
							this.dialog.hide();
							return;
						}

						const failed = res.failed || [];
						frappe.msgprint({
							title: __("Cash Coding Complete"),
							indicator: failed.length ? "orange" : "green",
							message: `
								<p>${__("Coded {0} of {1}.", [
									(res.created || []).length,
									selected.length,
								])}</p>
								${
									failed.length
										? `<p>${__("Failed")}: ${frappe.utils.escape_html(
												failed.join(", ")
										  )}</p>
										   <p class="text-muted">${__(
												"See Error Log for details."
										   )}</p>`
										: ""
								}
							`,
						});

						// Refresh the list in place so the user can keep coding.
						this.load_rows();
						this.refresh_tool();
					},
				});
			}
		);
	}

	refresh_tool() {
		// Open apps/erpnext/.../bank_reconciliation_tool.js and use whichever
		// handler rebuilds the datatable — usually the bank_account trigger.
		this.frm.trigger("bank_account");
	}
}