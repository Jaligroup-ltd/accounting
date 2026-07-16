## Jalipartners App

Custom Frappe/ERPNext v15 app for **Jali Partners** — the accounting platform behind
`accounting.jalikoi.rw`, serving our accounting farms.

Everything that customises  ERPNext lives in this app rather than in ad-hoc UI edits,
so that a fresh clone plus `bench migrate` reproduces the full setup and every change is
reviewable in Git.

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app jalipartners
```

### Deployment

Develop locally → push to GitHub → pull on the server. GitHub carries the code; `bench backup`
and restore carry the database and files.

```bash
cd /var/www/frappe-bench/apps/jalipartners
git pull
cd /var/www/frappe-bench
bench --site accounting.jalikoi.rw migrate
bench restart          # prod: sudo supervisorctl restart all
```

Python-only changes (no fixtures, no schema) need only `clear-cache` + `restart`. Asset
changes (`public/js`, `public/css`, images) need `bench build --app jalipartners`.

---

## Module map

The package is **flat** — modules sit directly under `jalipartners/jalipartners/`, so the
importable path is `jalipartners.<module>`

| File | Purpose |
|---|---|
| `hooks.py` | Central wiring: branding, `doc_events`, `override_whitelisted_methods`, `before_migrate` / `after_migrate`, fixtures, JS/CSS includes |
| `utils.py` | Role-tier enforcement — company scoping and the submit/cancel/delete guards |
| `branding.py` | Re-asserts Jali logo/favicon/splash on every migrate |
| `currency.py` | Exchange-rate provider override (RWF-aware) |
| `dashboard.py` | `get_ar_ageing` — AR ageing chart source |
| `dashboard_company.py` | `set_dashboard_company` — the Home company selector's setter |
| `bank_feed_api.py` | Current bank feed: `BANK_FEEDS` registry, dispatch, realtime notify |
<!-- | `api.py` | **Legacy** — the original I&M-only bank feed glue, superseded by `bank_feed_api.py` (see below) | -->
| `setup/user_customization.py` | Property Setters making Role Profile mandatory + filtered |
| `modules.txt` / `patches.txt` | Frappe module registry and patch list |
| `public/js/company_restriction.js` | Auto-sets user's company on forms, hides the field |
| `fixtures/` | Workspace, Custom Field, Custom HTML Block exports |

---

## Role hierarchy

Four tiers, enforced in `utils.py`:

```
Super Admin      → all companies, all powers
Company Admin    → one company, full powers incl. cancel/amend/delete
Company Staff    → one company, create + submit, no cancel/delete
Company Basic    → one company, drafts only — no submit
```

> **Frappe permissions are additive — the most permissive role always wins.** Restrictions
<!-- > that role config can't express are enforced server-side via `doc_events` hooks, not by
> ticking boxes in Role Permissions Manager. Operational users must **never** hold
> `System Manager`, which bypasses User Permissions entirely. -->

`before_submit` guards are wired per-doctype (Sales Invoice, Purchase Invoice, Payment Entry,
Journal Entry, Delivery Note, Sales Order, Purchase Order, Stock Entry). Note that
`frappe.has_permission(..., "submit")` still returns `True` for Company Basic — the block
happens at `before_submit`, not at the permission layer. That's expected, not a bug.

`setup/user_customization.py` runs on `after_migrate` and installs Property Setters that make
Role Profile mandatory on User and filter the dropdown to the four approved profiles. Since
`User` is a core DocType, this uses `frappe.make_property_setter` rather than Customize Form.

---

## Currency

`currency.py` overrides Frappe's exchange-rate lookup via `override_whitelisted_methods`:

- **RWF pairs → `open.er-api.com`** — Frankfurter does not support RWF.
- Everything else → Frankfurter.
- Same-currency guard: `return 1.0` when `from_currency == to_currency`.

Base currency is RWF. Per-customer currency restriction is
handled by the `Customer Allowed Currency` child table on Customer.

RRA VAT is 18%. For VAT-inclusive totals, back-calculate with `VAT = Total × (18 ÷ 118)` —
**not** `Total × 0.18`.

---

## Branding

`branding.py` runs on `before_migrate` and writes the logo path directly with
`frappe.db.set_value` on Website Settings (`favicon`, `splash_image`) and Navbar Settings
(`app_logo`).

This is deliberate. The `hooks.py` fallbacks only apply when those DB fields are empty, and
ERPNext's own hooks can win that race — which is how the ERPNext "E" kept coming back. Setting
the values explicitly on every migrate makes it permanent. It's also a surgical `set_value`
rather than a fixture, so it doesn't clobber unrelated Website Settings.

Portal chrome is stripped via `website_context` in `hooks.py` (`footer_powered: ""`,
`hide_footer_signup: True`). These are **site-global**, not per-company.

---

## Dashboard

**AR ageing chart.** `dashboard.py` exposes the whitelisted `get_ar_ageing`, which buckets
outstanding receivables into Current / 1–30 / 31–60 / 61–90 / 90+ by calling ERPNext's own
`accounts_receivable` report rather than querying the GL directly. It returns
`{labels, datasets}`, so a Dashboard Chart with Source = `Custom` renders it as-is. Falls back
to the user's default Company when none is passed.

The labels map `range1`→Current, `range2`→1-30 and so on, which assumes the report's default
`range1=30` means "0–30 days". If those ranges are ever re-tuned, the labels must move with
them.

**Company selector.** `dashboard_company.py` holds the setter:

```
jalipartners.dashboard_company.set_dashboard_company
```

The selector itself is a **Custom HTML Block** (`filter_home_by_company`) — a DB record edited
at `/app/custom-html-block`, dropped onto the top of the Home workspace, and persisted through
migrate via `fixtures` in `hooks.py`:

```python
fixtures = [
    {"doctype": "Custom HTML Block", "filters": {"name": ["in", ["filter_home_by_company"]]}},
]
```

Its script writes the user default that standard Number Cards already read, which is why no
card edits were needed — standard cards have locked filters and can't be edited directly. Two
consequences worth knowing:

- Setting the user's default Company also changes what's pre-filled on **new documents**
  (invoices, payments). For an admin switching context that's usually desirable, but it's a
  real change, not a view-only filter.
- Any card or chart that doesn't filter on `get_user_default("Company")` won't follow the
  selector. If one doesn't update, check that widget individually.

Re-export after UI edits: `bench --site accounting.jalikoi.rw export-fixtures`, then commit the
generated JSON.

---

## Bank Feed integration

Adds a **"Fetch from Bank"** dropdown to the **Bank Reconciliation Tool**, so bank statements
can be pulled on demand from Desk. Picking a bank runs that bank's automation and posts the
transactions back as **Bank Transaction** records (Unreconciled), ready to reconcile.

This app contains only the *ERPNext side*. The actual portal scraping/parsing lives in the
separate **`bank_feed_automation`** project (`imbank.py`, `bkbank.py`, `erpnext_import.py`),
which runs as localhost-only services alongside the bench. See that project's
`DEPLOY_ubuntu.md` for its setup.

> **`api.py` is the previous generation of this feature and is superseded.** It predates the
> multi-bank registry: I&M only, `imbank_service_url` / `imbank_service_token`, `Bearer` auth,
> and the `imbank_feed_done` / `imbank_feed_toast` events. `bank_feed_api.py` uses
> `bank_feed_service_token`, `token` auth, and `bank_feed_done`. **The two are not
> interchangeable** — the setup below configures `bank_feed_api.py` only. If nothing calls
> `jalipartners.api.trigger_fetch` any more, delete `api.py` rather than leave it to confuse
> the next reader.

### How it works

```
Bank Reconciliation Tool
  └─ Client Script "bank_reconciliation_tool.js"   ("Fetch from Bank" dropdown)
       └─ jalipartners/bank_feed_api.py
            ├─ get_bank_feeds()   -> the dropdown entries (from the BANK_FEEDS registry)
            ├─ trigger_fetch()    -> enqueues a background job (returns immediately)
            └─ _run_fetch()       -> POSTs to the bank's local service, then toasts the user
                 ├─ 127.0.0.1:8899/fetch  -> I&M Bank
                 └─ 127.0.0.1:8898/fetch  -> Bank of Kigali
```

The job posts `{from_date, to_date}` (taken from the tool's From/To Date fields) with an
`Authorization: token <bank_feed_service_token>` header. The work is enqueued on the `long`
queue rather than run inline, because a scrape takes 30–60s and would otherwise block the web
worker. Completion is reported back to the triggering user via
`frappe.publish_realtime("bank_feed_done", ...)`.

### Setup

**1. Site config.** Add the shared secret to `sites/<site>/site_config.json`. It must match
`BANK_FEED_SERVICE_TOKEN` in the `bank_feed_automation` project's `.env`:

```json
"bank_feed_service_token": "<long random string>"
```

Generate one with `openssl rand -hex 32`.

**2. Client Script.** Client Scripts live in the database, so they don't ship with this repo —
create it per site: **Client Script → New**, DocType = `Bank Reconciliation Tool`, Type =
`Form`, paste `bank_reconciliation_tool.js`, Enable. Set its `BANK_FEED_API` constant to the
dotted path of this module. Verify the path first:

```bash
bench --site <site> console
>>> import frappe; frappe.get_attr("jalipartners.bank_feed_api.get_bank_feeds")
```

**3. Masters.** Create the **Bank** and **Bank Account** records for each bank. Their names
must match `ERPNEXT_BANK_ACCOUNT` (I&M) and `BK_ERPNEXT_BANK_ACCOUNT` (BK) in the automation's
`.env`.

**4. Reload.**

```bash
bench --site <site> clear-cache
bench restart
```

### Adding another bank

One entry in `BANK_FEEDS` in `bank_feed_api.py` — the dropdown and dispatch both read from it,
so no Client Script change is needed:

```python
BANK_FEEDS = {
    "imbank": {"label": "I&M Bank",       "service_url": "http://127.0.0.1:8899/fetch"},
    "bkbank": {"label": "Bank of Kigali", "service_url": "http://127.0.0.1:8898/fetch"},
    "equity": {"label": "Equity Bank",    "service_url": "http://127.0.0.1:8897/fetch"},
}
```

The new bank also needs its own service + script in the `bank_feed_automation` project, and a
matching Bank Account master.

### Usage

Bank Reconciliation Tool → pick the Bank Account and From/To dates → **Fetch from Bank** →
choose the bank. A blue toast confirms it started; a green toast reports how many
transactions posted. Then **Get Unreconciled Entries**.

> Each trigger performs a real login at the bank's portal. Bank of Kigali sends an OTP per
> login and rate-limits rapid repeats — don't hammer the button.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Dropdown is empty / doesn't appear | `BANK_FEED_API` path wrong in the Client Script — verify with `frappe.get_attr` |
| Click → 500 | Bad module path, or Redis/workers down (`bench doctor`) |
| Toast: `401 Unauthorized` from the service | `bank_feed_service_token` ≠ the service's `BANK_FEED_SERVICE_TOKEN`; restart both sides after editing |
| Toast: `500` from the service | The scraper itself failed — check that project's logs / `journalctl -u <svc>` |
| Job queued but never finishes | Workers not running; check `bench doctor` / `supervisorctl status` |
| No toast at all | Import may still have worked — check the socketio process |
| `Connection refused` | The bank's service isn't running; `curl http://127.0.0.1:889X/health` |

Errors from the enqueued job land in Desk → **Error Log**.

> **Reconciliation gotcha:** the Bank Reconciliation Tool needs Bank Transaction records *and*
> a populated **Company Bank Account** field on the Payment Entry. The GL account field alone
> is not enough for Auto Reconcile to match.

---

## Conventions

- **Production-grade customisations belong in this app and repo** — fixtures, hooks and Python
  modules survive `bench migrate`; UI edits don't.
- `before_migrate` for branding/setup that must be re-asserted; `after_migrate` for Property
  Setters and role scaffolding.
- Anything importable as `jalipartners.X` must live inside `apps/jalipartners/jalipartners/`,
  not next to `setup.py`. The double-nested layout catches people out.
- Console-first diagnostics: `bench --site accounting.jalikoi.rw console` before changing code.
- Opening invoices go through the **Opening Invoice Creation Tool** (not Data Import) to
  preserve AR/AP aging; remaining balances via an Opening Journal Entry with `Is Opening = Yes`.

---

## Contributing

This app uses `pre-commit` for formatting and linting:

```bash
cd apps/jalipartners
pre-commit install
```

Hooks: **ruff**, **ruff-format**, **eslint**, **prettier**, **pyupgrade**.

> Install pre-commit with **pipx**, outside the bench virtualenv — `pip install pre-commit`
> inside it upgrades `filelock` / `python-dateutil` past Frappe's pins.

CI runs pre-commit in *check* mode, so any modification is a failure. Run
`pre-commit run --all-files` locally before pushing. Note ruff-format converts indentation to
**tabs** (Frappe house style) — set your editor accordingly (`"editor.insertSpaces": false`) so
you're not fighting it on every edit.

### CI

GitHub Actions — `ci.yml` (installs the app and runs unit tests on push to `develop`) and
`linter.yml` ([Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and
[pip-audit](https://pypi.org/project/pip-audit/) on every PR).

Two things the pipeline is sensitive to:

- `bench init` **must** include `--frappe-branch version-15`. Omit it and it silently pulls
  `develop`, which uses Python 3.12+ syntax and breaks against the v15 stack.
- The apt package is **`mariadb-client`** — no version suffix — on newer Ubuntu runners.

### License

mit