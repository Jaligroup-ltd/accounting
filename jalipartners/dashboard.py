import frappe
from erpnext.accounts.report.accounts_receivable.accounts_receivable import execute as ar_execute
from frappe.utils import nowdate


@frappe.whitelist()
def get_ar_ageing(company=None):
	if not company:
		company = frappe.defaults.get_user_default("Company")

	filters = frappe._dict(
		{
			"company": company,
			"report_date": nowdate(),
			"ageing_based_on": "Posting Date",
			"range1": 30,
			"range2": 60,
			"range3": 90,
			"range4": 120,
			"party_type": "Customer",
		}
	)

	columns, data, *_ = ar_execute(filters)

	buckets = {"Current": 0, "1-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
	# Note: in AR report, range1 = 0-30 by default. Adjust labels to taste.
	for row in data:
		if not isinstance(row, dict):
			continue
		# Skip total/summary rows — they typically have no party
		if not row.get("party"):
			continue
		buckets["Current"] += row.get("range1", 0) or 0
		buckets["1-30"] += row.get("range2", 0) or 0
		buckets["31-60"] += row.get("range3", 0) or 0
		buckets["61-90"] += row.get("range4", 0) or 0
		buckets["90+"] += row.get("range5", 0) or 0

	return {
		"labels": list(buckets.keys()),
		"datasets": [
			{
				"name": "Outstanding",
				"values": [round(v, 2) for v in buckets.values()],
			}
		],
	}
