import json

import frappe
from frappe import _
from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
	create_journal_entry_bts,
)

MAX_SYNC_ROWS = 40


@frappe.whitelist()
def get_uncoded_transactions(bank_account, from_date, to_date, search=None):
	filters = {
		"bank_account": bank_account,
		"docstatus": 1,
		"status": ["!=", "Reconciled"],
		"unallocated_amount": [">", 0],
		"date": ["between", [from_date, to_date]],
	}
	if search:
		filters["description"] = ["like", f"%{search}%"]

	return frappe.get_all(
		"Bank Transaction",
		filters=filters,
		fields=[
			"name",
			"date",
			"description",
			"reference_number",
			"currency",
			"deposit",
			"withdrawal",
			"unallocated_amount",
		],
		order_by="date asc, name asc",
		limit_page_length=500,
	)


@frappe.whitelist()
def bulk_cash_code(
	transactions,
	account,
	party_type=None,
	party=None,
	mode_of_payment=None,
	entry_type="Bank Entry",
):
	names = json.loads(transactions) if isinstance(transactions, str) else transactions
	if not names:
		frappe.throw(_("No transactions selected"))

	if not frappe.has_permission("Journal Entry", "create"):
		frappe.throw(_("Not permitted to create Journal Entries"))

	if frappe.db.get_value("Account", account, "account_type") in ("Receivable", "Payable"):
		frappe.throw(
			_("Cash coding cannot post to receivable or payable accounts — these need a party.")
		)

	if len(names) > MAX_SYNC_ROWS:
		frappe.enqueue(
			"jalipartners.cash_coding._run_bulk_cash_code",
			queue="long",
			timeout=1800,
			names=names,
			account=account,
			party_type=party_type,
			party=party,
			mode_of_payment=mode_of_payment,
			entry_type=entry_type,
			user=frappe.session.user,
		)
		return {"queued": True, "count": len(names)}

	return _run_bulk_cash_code(
		names, account, party_type, party, mode_of_payment, entry_type
	)


def _run_bulk_cash_code(
	names,
	account,
	party_type=None,
	party=None,
	mode_of_payment=None,
	entry_type="Bank Entry",
	user=None,
):
	result = {"created": [], "failed": []}

	for name in names:
		try:
			bt = frappe.db.get_value(
				"Bank Transaction",
				name,
				["date", "reference_number"],
				as_dict=True,
			)
			if not bt:
				raise frappe.DoesNotExistError(f"Bank Transaction {name} not found")

			create_journal_entry_bts(
				bank_transaction_name=name,
				posting_date=bt.date,
				reference_date=bt.date,
				reference_number=bt.reference_number,
				entry_type=entry_type,
				second_account=account,
				party_type=party_type,
				party=party,
				mode_of_payment=mode_of_payment,
			)
			frappe.db.commit()
			result["created"].append(name)
		except Exception:
			frappe.db.rollback()
			frappe.clear_messages()
			frappe.log_error(
				title=f"Cash coding failed: {name}",
				message=frappe.get_traceback(),
			)
			result["failed"].append(name)

	if user:
		frappe.publish_realtime("cash_coding_done", result, user=user)

	return result