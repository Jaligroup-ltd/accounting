# Bank reconciliation extensions

> Part of **IAS**. See the [README](../README.md) for the module map, the role
> hierarchy and the conventions every feature here assumes.

Stock ERPNext offers three actions on a bank transaction (Match Against Voucher, Create
Voucher, Update Bank Transaction), each operating on one transaction at a time. Two gaps
showed up once the finance team moved off Xero: coding dozens of small statement lines one by
one, and recording a movement between two company bank accounts.

## Cash Coding

A **Cash Coding** button on the Bank Reconciliation Tool opens a dialog listing every
unreconciled transaction for the selected bank account and statement period, with a debounced
description filter, per-row checkboxes, an indeterminate-aware select-all, a live selection
count, and a single account picker. Ticked rows are posted as Journal Entries of type *Bank
Entry* against that one account.

| Path | Purpose |
|---|---|
| `jalipartners/cash_coding.py` | `get_uncoded_transactions`, `bulk_cash_code` |
| `jalipartners/public/js/cash_coding.js` | The button and dialog |
| `hooks.py` | Registers the form script |

```python
# Loaded only when the Bank Reconciliation Tool form is opened.
doctype_js = {
    "Bank Reconciliation Tool": "public/js/cash_coding.js",
}
```

The path is relative to the inner app folder (`jalipartners/jalipartners/`), so it is
`public/js/cash_coding.js` and **not** `jalipartners/public/js/cash_coding.js`. Getting this
wrong is the usual reason the button never appears.

**Design notes.**

- The dialog renders its own markup into an `HTML` field's `$wrapper` rather than extending
  ERPNext's DataTable. Enabling `checkboxColumn` on that grid means overriding
  `get_datatable()` in `data_table_manager.js`, which is a fork of ERPNext internals that
  would break silently on a version bump. As written, the feature depends on one whitelisted
  Python function.
- Every interpolated value passes through `frappe.utils.escape_html`. Descriptions come
  straight from the BK Playwright scrape and routinely contain characters that would break the
  row or worse.
- The server **commits per row**. Without it, one bad transaction (a closed period, a missing
  mandatory value) rolls back an entire batch of otherwise-valid entries. A partial batch
  succeeds and the failures come back named. The failure path calls `frappe.clear_messages()`.
- Above a 40-row threshold the work is queued rather than run synchronously.
- Each transaction is passed to ERPNext's `create_journal_entry_bts()`, with `posting_date`
  read off the bank transaction and passed explicitly.
- `update_primary()` keeps the submit button disabled until at least one row is ticked and an
  account chosen; submitting an empty selection throws a server error.
- `refresh_tool()` calls `frm.trigger("bank_account")` to rebuild the datatable behind the
  dialog. `frm.refresh()` alone does nothing, because the transaction list is rendered
  imperatively rather than from `frm.doc`.

**Guard rails.**

> Cash Coding posts the **gross** statement amount to one account. Under RRA rules that is
> wrong for deductible purchases. The feature is for non-VAT lines only (bank charges, mobile
> money fees, interest, commissions). VAT-bearing spend goes through Purchase Invoices, where
> the 18/118 back-calculation applies.

- Receivable and Payable accounts are blocked on the client **and again** in `bulk_cash_code`.
  The client filter can be bypassed by calling the whitelisted method directly, and customer
  deposits coded to income leave the invoices open, which is expensive to unpick at year end.
- The account picker is deliberately narrow: non-group Expense and Income accounts for the
  current company only. Bank and transit accounts do not appear, and that is intended. Widen
  `root_type` in the `get_query` if a genuine asset or liability case ever appears.
- `bulk_cash_code` checks `Journal Entry: create` server-side before posting. Under the
  five-tier role model that means Company Staff and above since
  entries are submitted immediately rather than left in draft.

**Deploying a change.**

```bash
git pull
bench build --app jalipartners
bench migrate
bench clear-cache
bench restart
```

Hard-reload the browser afterwards. Frappe caches form-script bundles aggressively and an
ordinary refresh keeps serving the old one, which looks exactly like a deployment that
silently failed. There is no feature-specific configuration.

## Transfer action (internal transfers between company bank accounts)

A movement between two of our own bank accounts is a Payment Entry of type *Internal
Transfer*. Nothing new is invented on the accounting side; `paid_from` and `paid_to` carry the
real bank accounts and no intermediate account appears in the chart of accounts. Funds in
Transit was considered and rejected.

| Path | Purpose |
|---|---|
| `jalipartners/bank_reconciliation_transfer.py` | Creates or finds the Payment Entry and allocates it to the bank transaction |
| `jalipartners/public/js/bank_reconciliation_transfer.js` | Adds the Transfer option and its fields to the reconciliation dialog |

**One transfer is one Payment Entry, allocated to both statement lines.** That is the whole
design, and it is why the action behaves differently depending on which leg it is standing on:
create the voucher on the first leg, find and link it on the second. `find_existing_transfer()`
does that lookup, filtered on amount, a seven-day date window, and the GL account pair using
`in` rather than directional filters, with a `not in` exclusion list so a voucher already
linked to a transaction on *this* bank account is never picked up again.

The client side **monkey-patches `DialogManager`** (`get_dialog_fields()` and
`reconciliation_dialog_primary_action()`). That is the fragile part of the build, and the
reason the upgrade checklist below exists.

**Both routes are live.** The finance team also creates Internal Transfer Payment Entries by
hand (Accounting → Payment Entry → New, Payment Type = Internal Transfer, the two bank accounts
in Account Paid From / Paid To, then **Match Against Voucher** in the reconciliation tool) and
that is currently the usual route. Documenting both is deliberate, but two routes to one
voucher is itself a duplication risk. Pick one before the finance team grows.

> **Second-leg trap.** A transfer produces two statement lines: a withdrawal on one bank and a
> deposit on the other, both answered by one Payment Entry. ERPNext's `get_pe_matching_query`
> filters on `ifnull(clearance_date, '') = ""`, so once the first leg is reconciled the voucher
> is stamped with a clearance date and disappears from the matching list on the second leg. The
> Transfer action does not care, because it appends to the child table directly rather than
> going through matching, and that is exactly the trap: run Transfer on a second leg it fails
> to match and it creates a *second* Payment Entry, recording the transfer twice.
>
> Read the message on screen. "Matched to existing transfer" on the second line is the only
> thing standing between the team and a silent duplicate. "Transfer created" twice means a
> duplicate exists. The realistic causes are a deducted bank charge making the two amounts
> differ, and legs more than a week apart (the window).
>
> Month-end check: scan Internal Transfer Payment Entries for duplicate amount/date pairs.

```bash
bench --site accounting.jalikoi.rw console
```

## Upgrade checklist

Run through this on any ERPNext minor or major bump. Both features depend on internals that are
stable but not contractual.

1. `create_journal_entry_bts()` keyword signature:
   `grep -A 15 "def create_journal_entry_bts" apps/erpnext/erpnext/accounts/doctype/bank_reconciliation_tool/bank_reconciliation_tool.py`.
   Keyword names have moved between v14 and v15.
2. `erpnext.accounts.bank_reconciliation.DialogManager` still exists, and `get_dialog_fields()`
   / `reconciliation_dialog_primary_action()` are still the method names being patched.
3. The property the dialog stores the current transaction on. Some builds keep the document,
   others only the name.
4. `payment_entries` is still `allow_on_submit` on Bank Transaction, since the transfer method
   saves a submitted document.
5. `refresh_tool()` still triggers the handler that rebuilds the datatable.

