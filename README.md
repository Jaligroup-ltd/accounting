# IAS (In-House Accounting Software)

Custom Frappe/ERPNext v15 app behind **IAS**, Jalipartner's in-house accounting software,
served at `accounting.jalikoi.rw` for our accounting farms.

Everything that customises ERPNext lives in this app rather than in ad-hoc UI edits, so that
a fresh clone plus `bench migrate` reproduces the full setup and every change is reviewable
in Git.

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app jalipartners
```

### Deployment

Develop locally, push to GitHub, then deploy. GitHub carries the code; `bench backup` and
restore carry the database and files.

Pushes to `develop` that pass CI trigger `deploy.yml`, which pulls on the server and clears
the cache (see [CI/CD](#cicd)). Manual deployment as the `frappe` user remains available and
is still the route for anything needing a migrate or a build:

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

The package is **flat**: modules sit directly under `jalipartners/jalipartners/`, so the
importable path is `jalipartners.<module>`

| File | Purpose |
|---|---|
| `hooks.py` | Central wiring: branding, `doc_events`, `override_whitelisted_methods`, `doctype_js`, `before_migrate` / `after_migrate`, fixtures, JS/CSS includes |
| `utils.py` | Role-tier enforcement: company scoping and the submit/cancel/delete guards |
| `branding.py` | Re-asserts Jali logo/favicon/splash on every migrate; also re-asserts the POS workspace label |
| `currency.py` | Exchange-rate provider override (RWF-aware) |
| `dashboard.py` | `get_ar_ageing`, the AR ageing chart source ([docs](docs/dashboard.md)) |
| `dashboard_company.py` | `set_dashboard_company`, the Home company selector's setter ([docs](docs/dashboard.md)) |
| `bank_feed_api.py` | Current bank feed: `BANK_FEEDS` registry, dispatch, realtime notify ([docs](docs/bank-feeds.md)) |
| `bank_credentials_api.py` | Serves bank portal and mailbox logins to the scraper services: `ping`, `get_credentials`, `get_fingerprints` ([docs](docs/bank-credentials.md)) |
| `cash_coding.py` | Bulk coding of bank statement lines: `get_uncoded_transactions`, `bulk_cash_code` ([docs](docs/bank-reconciliation.md)) |
| `bank_reconciliation_transfer.py` | Creates or finds the Internal Transfer Payment Entry and allocates it to the bank transaction ([docs](docs/bank-reconciliation.md)) |
| `setup/user_customization.py` | Property Setters making Role Profile mandatory + filtered |
| `modules.txt` / `patches.txt` | Frappe module registry and patch list |
| `public/js/company_restriction.js` | Auto-sets user's company on forms, hides the field |
| `public/js/cash_coding.js` | Cash Coding button and dialog on the Bank Reconciliation Tool ([docs](docs/bank-reconciliation.md)) |
| `public/js/bank_reconciliation_transfer.js` | Monkey-patches `DialogManager` to add the Transfer option to the reconciliation dialog ([docs](docs/bank-reconciliation.md)) |
| `fixtures/` | Workspace, Custom Field, Print Format, Custom HTML Block exports |
| `fixtures/` (Print Format) | Sales Invoice and POS receipt layouts ([docs](docs/print-formats.md)) |

---

## Role hierarchy


Four tiers, enforced in `utils.py`:

```
Super Admin      -> all companies, all powers
Company Admin    -> one company, full powers incl. cancel/amend/delete
Company Staff    -> one company, create + submit, no cancel/delete
Company Basic    -> one company, drafts only, no submit
Credentials Feeder-> Feeds only bank credentials to the bank_feed_automation project
```

> **Frappe permissions are additive; the most permissive role always wins.** Restrictions that
> role config can't express are enforced server-side via `doc_events` hooks, not by ticking
> boxes in Role Permissions Manager. Operational users must **never** hold `System Manager`,
> which bypasses User Permissions entirely.

`before_submit` guards are wired per-doctype (Sales Invoice, Purchase Invoice, Payment Entry,
Journal Entry, Delivery Note, Sales Order, Purchase Order, Stock Entry). Note that
`frappe.has_permission(..., "submit")` still returns `True` for Company Basic; the block
happens at `before_submit`, not at the permission layer. That's expected, not a bug.

`setup/user_customization.py` runs on `after_migrate` and installs Property Setters that make
Role Profile mandatory on User and filter the dropdown to the five approved profiles. Since
`User` is a core DocType, this uses `frappe.make_property_setter` rather than Customize Form.

---

## Currency


`currency.py` overrides Frappe's exchange-rate lookup via `override_whitelisted_methods`:

- **RWF pairs go to `open.er-api.com`.** Frankfurter does not support RWF.
- Everything else goes to Frankfurter.
- Same-currency guard: `return 1.0` when `from_currency == to_currency`.

Base currency is RWF. Per-customer currency restriction is handled by the
`Customer Allowed Currency` child table on Customer.

RRA VAT is 18%. For VAT-inclusive totals, back-calculate with `VAT = Total × (18 ÷ 118)`,
**not** `Total × 0.18`.

---

## Branding


`branding.py` runs on `before_migrate` and writes the logo path directly with
`frappe.db.set_value` on Website Settings (`favicon`, `splash_image`) and Navbar Settings
(`app_logo`).

This is deliberate. The `hooks.py` fallbacks only apply when those DB fields are empty, and
ERPNext's own hooks can win that race, which is how the ERPNext "E" kept coming back. Setting
the values explicitly on every migrate makes it permanent. It's also a surgical `set_value`
rather than a fixture, so it doesn't clobber unrelated Website Settings.

Portal chrome is stripped via `website_context` in `hooks.py` (`footer_powered: ""`,
`hide_footer_signup: True`). These are **site-global**, not per-company.

---

## Features

Each feature has its own maintainer guide under `docs/`. They all assume the conventions below:
changes survive `bench migrate`, live in this repo, and are reviewable in Git.

| Guide | Covers |
|---|---|
| [Bank feed integration](docs/bank-feeds.md) | The **Fetch Statement** button, the `BANK_FEEDS` registry, and how a Bank Account routes to a scraper service |
| [Bank credentials](docs/bank-credentials.md) | The `Bank Credential` doctype, the role that guards it, the API the scrapers read, and the security trade it represents |
| [Bank reconciliation extensions](docs/bank-reconciliation.md) | Cash Coding, the Transfer action for internal transfers, and the ERPNext upgrade checklist for both |
| [Print formats](docs/print-formats.md) | The Xero-style Sales Invoice with its payment advice stub, the 80mm POS receipt, and the Jinja sandbox constraints |
| [Point of Sale](docs/pos.md) | POS Awesome configuration, cashier onboarding, offline behaviour and its limits |
| [Dashboard](docs/dashboard.md) | The AR ageing chart and the Home company selector |

Each guide follows the same shape: what it does, its files, setup, usage, gotchas,
troubleshooting, and an upgrade checklist where one applies. Several are paired with a Word
user guide for the finance team; the dev guide links it at the top. Change one, change both.

---

## Conventions


- **Production-grade customisations belong in this app and repo.** Fixtures, hooks and Python
  modules survive `bench migrate`; UI edits don't.
- `before_migrate` for branding/setup that must be re-asserted; `after_migrate` for Property
  Setters and role scaffolding.
- Anything importable as `jalipartners.X` must live inside `apps/jalipartners/jalipartners/`,
  not next to `setup.py`. The double-nested layout catches people out, and `doctype_js` paths
  are relative to that inner folder.
- Console-first diagnostics: `bench --site accounting.jalikoi.rw console` before changing code.
- Third-party apps (POS Awesome) stay out of this repo, but anything they need *configured*
  (workspace labels, branding, Property Setters) is re-asserted from here on migrate. Pin the
  fork and commit; treat an unpinned dependency as an upgrade blocker.
- Opening invoices go through the **Opening Invoice Creation Tool** (not Data Import) to
  preserve AR/AP aging; remaining balances via an Opening Journal Entry with `Is Opening = Yes`.
- Custom fields go through **Customize Form** and are exported as fixtures, never through the
  raw DocType editor. The raw editor does not survive an ERPNext upgrade.
- New features ship with two documents: an in-repo Markdown maintainer guide and a Word user
  guide in Jali house style for the finance team.

---

## Contributing


This app uses `pre-commit` for formatting and linting:

```bash
cd apps/jalipartners
pre-commit install
```

Hooks: **ruff**, **ruff-format**, **eslint**, **prettier**, **pyupgrade**.

> Install pre-commit with **pipx**, outside the bench virtualenv. `pip install pre-commit`
> inside it upgrades `filelock` / `python-dateutil` past Frappe's pins.

CI runs pre-commit in *check* mode, so any modification is a failure. Run
`pre-commit run --all-files` locally before pushing. Note ruff-format converts indentation to
**tabs** (Frappe house style), so set your editor accordingly (`"editor.insertSpaces": false`)
and you won't be fighting it on every edit.

### CI/CD

GitHub Actions, three workflows:

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | push to `develop`, PRs | Installs the app and runs unit tests against MariaDB + Redis |
| `linter.yml` | PRs | [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) |
| `deploy.yml` | `workflow_run` after CI passes | `git pull` on the current branch, then `bench --site accounting.jalikoi.rw clear-cache`, then a health check |

`deploy.yml` deliberately does **not** run `migrate` or `build`. Anything touching fixtures,
schema or assets is deployed by hand as the `frappe` user.

**Deploy access.** A dedicated least-privilege user `ghdeploy` holds the Actions key, pinned to
a root-owned deploy script by an SSH forced-command in `authorized_keys` plus a scoped sudoers
rule. The `frappe` user is untouched and remains the manual-deployment route.

Things the pipeline is sensitive to:

- `bench init` **must** include `--frappe-branch version-15`. Omit it and it silently pulls
  `develop`, which uses Python 3.12+ syntax and breaks against the v15 stack.
- The apt package is **`mariadb-client`**, no version suffix, on newer Ubuntu runners.
- The server's git remote must be **SSH, not HTTPS**. An HTTPS remote has no credential in a
  non-interactive context and `git pull` fails inside the deploy script. The `frappe` user needs
  its own GitHub deploy key, a `~/.ssh/config` entry, and GitHub's host fingerprint
  pre-accepted.
- The org's free-tier Actions minutes (2,000/month, $0 spending limit) can be exhausted, which
  blocks every job. Mitigation is a self-hosted runner on the existing droplet.
