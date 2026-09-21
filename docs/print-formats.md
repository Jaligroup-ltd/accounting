# Print formats

> Part of **IAS**. See the [README](../README.md) for the module map, the role
> hierarchy and the conventions every feature here assumes.

Invoices were rebuilt to match the Xero layout the finance team came from, so the change of
system is not also a change of paperwork. The formats themselves ship as fixtures.

> This guide replaces the old top-level `PRINT_FORMATS.md`. Move anything still only in that
> file here, then delete it: two maintainer guides for one feature is how they start
> disagreeing.

| Format | DocType | Notes |
|---|---|---|
| `Jalipartners Sales Invoice` | Sales Invoice | Logo above a three-column header, stacked invoice meta labels, amount in words, and a tear-off **Payment Advice** stub |
| Jali POS Receipt | POS Invoice | 80mm thermal, logo centred at top |

Constraints that cost real time to find, and that any edit has to respect:

- **`frappe.parse_json` is not whitelisted** in Frappe's Jinja sandbox. It renders as an error,
  not a blank.
- **`company_registration_no` lives on Company, not Sales Invoice.** Reading it off `doc`
  silently yields nothing.
- **`Address.get_display()` is unreliable** inside the sandbox; build the address from fields.
- **Do not hardcode 18% on item lines.** It is an RRA compliance risk the moment a zero-rated
  or exempt line appears. Read the tax actually applied.
- `registration_details` holds a multi-line address block, not a registration number, so it
  does not belong in the footer fallback chain.
- Frappe's print stylesheet bleeds borders into label cells; override explicitly.
