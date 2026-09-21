# Point of Sale (POS Awesome)

> Part of **IAS**. See the [README](../README.md) for the module map, the role
> hierarchy and the conventions every feature here assumes.

Retail/forecourt selling runs on **POS Awesome**, a Vue.js POS front end installed as a
separate Frappe app. It is *not* part of this repo and is not version-controlled here; it is
pulled from its upstream fork. What lives in this app is the ERPNext-side configuration that
has to survive `bench migrate`: the workspace label and the company branding the POS screen
reads.

POS Awesome is a **front end, not an accounting engine**. Every completed sale is a standard
**POS Invoice**, posting to the same GL accounts, drawing stock from the same Warehouse, and
running through the same `utils.py` role guards and `currency.py` exchange-rate override as
everything else. When a sale looks wrong, suspect ordinary ERPNext causes (draft docstatus,
company filter, date range, cancellation) before suspecting the POS app.

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/defendicon/POS-Awesome-V15 
bench --site accounting.jalikoi.rw install-app posawesome
bench build --app posawesome
bench --site accounting.jalikoi.rw migrate
bench restart
```

> Front-end edits need `bench build --app posawesome` **before** `restart`. The Vue bundle is
> compiled at build time, so a source change with no rebuild silently does nothing. This is the
> single most common reason a POS fix "doesn't take".

## Configuration

The POS Profile is the control record for a terminal: it binds company, warehouse, price list,
payment modes and permitted users. One profile and one **Warehouse** per station. Stock moved
between stations goes through a Stock Entry of type *Material Transfer*, never the POS screen.

| Setting | Where | Notes |
|---|---|---|
| Company / Warehouse | POS Profile | Must be the real trading entity, not a demo company |
| Applicable Users | POS Profile | Once **any** user is listed, no one else can open that profile |
| Write Off Account | POS Profile | Absorbs small cash rounding differences up to the write-off limit, **not** bad debt. Expense ledger under Indirect Expenses; keep the limit low enough that it can't mask a real shortfall |
| Stock Adjustment Account | Chart of Accounts | Ledger under **Expenses → Direct Expenses**, `Account Type = Stock Adjustment`. Setting the account *type* is what makes ERPNext pick it automatically on Stock Reconciliation; naming alone does nothing |
| Cashier PIN | **User** doctype | A field POS Awesome adds. Not the login password, not auto-generated |
| Company Logo | **Company** doctype | Drives the logo on the POS sidebar, see Branding below |

**Onboarding a cashier is two independent steps**, and omitting either produces the *same*
`Unable to verify cashier PIN` error at the terminal:

1. Set the PIN on that user's **User** record.
2. Add the user to **Applicable Users** on the POS Profile for their terminal.

## Branding

The logo beside the company name in the POS sidebar comes from the **Company Logo** field on
the **Company** record, not from POS Awesome, and not from `branding.py`'s Website/Navbar work.
Each entity carries its own, so a logo set on one company will not appear for another.

## Offline behaviour

Item, price and customer data are cached in browser local storage, so a terminal keeps billing
while the server is unreachable and syncs the queued invoices when it returns. Two limits worth
knowing before relying on it:

- Offline invoices live in **that browser** until sync. Clearing browser data on the terminal
  before sync loses them permanently.
- Offline stock validation is only as good as the cached position, so two terminals selling
  against one warehouse can produce a negative-stock condition that only surfaces on sync.

The persistent **Online / Offline** indicator in the POS navbar is authoritative. The transient
`Connection Lost` toasts are not: they currently stack (each failed connectivity check raises
its own instead of updating one in place), so treat pile-up as a cosmetic defect and the navbar
badge as the real signal.

> A genuine `Offline` badge on production is a **connectivity incident, not a UI bug**. Fix the
> toast stacking and investigate the outage separately; don't let the cosmetic fix suppress the
> symptom you actually want to see.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Sale missing from General Ledger | Invoice still in **draft**; drafts post nothing. Then check company, posting date vs report range, and cancellation |
| `Unable to verify cashier PIN` | No PIN set on the User record, **or** user not in Applicable Users on the profile |
| Front-end change has no effect | `bench build --app posawesome` not run before `restart` |
| Wrong / missing sidebar logo | Company Logo field on the relevant **Company**; then `clear-cache` + `clear-website-cache` |
| Item shows zero available qty | Stock sits in a different warehouse (or company) than the one on the POS Profile |
| Workspace reverts to "POS Awesome" | The `after_migrate` rename didn't run; app workspace sync won the race |
| `Connection Lost` toasts stacking | Cosmetic; guard flag needed in the front-end network watcher, then rebuild |

