# Bank feed integration

> Part of **IAS**. See the [README](../README.md) for the module map, the role
> hierarchy and the conventions every feature here assumes.

Adds a **Fetch Statement** button to the **Bank Reconciliation Tool**, so statements can be
pulled on demand from Desk. There is no bank dropdown: the feed is inferred from the **Bank
Account already selected** on the form, and the button only shows when that account has a feed
behind it. The fetch runs that bank's automation and posts the results back as **Bank
Transaction** records (Unreconciled), ready to reconcile.

This app contains only the *ERPNext side*. The actual portal scraping/parsing lives in the
separate **`bank_feed_automation`** project (`imbank.py`, `bkbank.py`, `mtnbank.py`,
`erpnext_import.py`), which runs as localhost-only services alongside the bench. See that
project's documentation for its setup, and [Bank credentials](bank-credentials.md) for how
those services get their logins.

> **`api.py` is the previous generation of this feature and is superseded.** It predates the
> multi-bank registry: I&M only, `imbank_service_url` / `imbank_service_token`, `Bearer` auth,
> and the `imbank_feed_done` / `imbank_feed_toast` events. `bank_feed_api.py` uses
> `bank_feed_service_token`, `token` auth, and `bank_feed_done`. **The two are not
> interchangeable**; the setup below configures `bank_feed_api.py` only. If nothing calls
> `jalipartners.api.trigger_fetch` any more, delete `api.py` rather than leave it to confuse
> the next reader.

## How it works

```
Bank Reconciliation Tool   (Bank Account already selected)
  └─ Client Script "bank_reconciliation_tool.js"
       └─ jalipartners/bank_feed_api.py
            ├─ feed_label_for_account(bank_account)
            │      -> the feed's label, or None: this is what shows/hides the button
            ├─ trigger_fetch_for_account(bank_account, from_date, to_date)
            │      └─ _feed_for_account()  -> matches the account against BANK_FEEDS[*]["accounts"]
            ├─ trigger_fetch(bank, ...)    -> enqueues on the long queue, returns immediately
            ├─ get_bank_feeds()            -> every feed; kept for reference or a manual UI
            └─ _run_fetch()                -> POSTs to the local service, then toasts the user
                 ├─ 127.0.0.1:8899/fetch  -> I&M Bank        ("IM Bank account - IM Bank")
                 ├─ 127.0.0.1:8898/fetch  -> Bank of Kigali  ("BK Bank - BK")
                 └─ 127.0.0.1:8897/fetch  -> MTN MoMo        ("MTN MoMo Account - MTN MoMo")
```

> **The Bank Account record name is the routing key.** Each registry entry lists the exact
> ERPNext Bank Account name(s) it reconciles, and `_feed_for_account` matches on that string.
> Rename a Bank Account and the button silently stops appearing for it. There is no error,
> because "this account has no feed" is a legitimate state. Update `BANK_FEEDS` in the same
> commit as any rename.

The job posts `{from_date, to_date}` (from the tool's From/To Date fields) with an
`Authorization: token <bank_feed_service_token>` header. It is enqueued on the `long` queue
rather than run inline, because a scrape takes 30-60s and would otherwise block the web worker:
job timeout 1500s, HTTP timeout to the service 1200s. Completion comes back to the triggering
user via `frappe.publish_realtime("bank_feed_done", ...)` with `after_commit=False`, so the
toast fires even though the job itself commits nothing. The message carries the `created` count
the service returns, or just "done" when it returns none.

`_RUN_FETCH_PATH` is derived from `__name__`, so the dotted path `frappe.enqueue` receives is
correct wherever the file is placed. Do not hardcode it back to a literal.

## Setup

**1. Site config.** Add the shared secret to `sites/<site>/site_config.json`. It must match
`BANK_FEED_SERVICE_TOKEN` in the `bank_feed_automation` project's `.env`:

```json
"bank_feed_service_token": "<long random string>"
```

Generate one with `openssl rand -hex 32`.

**2. Client Script.** Client Scripts live in the database, so they don't ship with this repo.
Create it per site: **Client Script → New**, DocType = `Bank Reconciliation Tool`, Type =
`Form`, paste `bank_reconciliation_tool.js`, Enable. It calls `feed_label_for_account` when the
Bank Account changes to decide whether to render the button, and `trigger_fetch_for_account` on
click. Verify the module path first:

```bash
bench --site <site> console
>>> import frappe; frappe.get_attr("jalipartners.bank_feed_api.feed_label_for_account")
```

**3. Masters.** Create the **Bank** and **Bank Account** records for each feed. The Bank Account
record name must match the `accounts` list in `BANK_FEEDS` **and** the corresponding
`*_ERPNEXT_BANK_ACCOUNT` value in the automation's `.env`. Three places, one string.

**4. Reload.**

```bash
bench --site <site> clear-cache
bench restart
```

## Adding another bank

One entry in `BANK_FEEDS` in `bank_feed_api.py`. Dispatch and button visibility both read from
it, so no Client Script change is needed:

```python
"equity": {
    "label": "Equity Bank",
    "service_url": "http://127.0.0.1:8896/fetch",
    "accounts": ["Equity Bank Account - Equity"],
},
```

Ports in use are 8899 (I&M), 8898 (BK) and 8897 (MTN MoMo), so a new service starts at 8896 and
counts down.

An account can be listed against only one feed, but a feed may list several accounts, which is
the route if one portal covers more than one ERPNext Bank Account.

The new bank also needs its own service + script in the `bank_feed_automation` project, a
matching Bank Account master, and a username/password field pair on the `Bank Credential`
DocType (see [Bank credentials](bank-credentials.md)).

## Usage

Bank Reconciliation Tool → pick Company and Bank Account → set From/To dates → **Fetch
Statement** → then **Get Unreconciled Entries**. A blue toast confirms the job started; a green
toast reports how many transactions posted.

If the button isn't there, the selected account has no feed configured. That is the intended
behaviour, not a fault.

> Each trigger performs a real login at the bank's portal. Bank of Kigali sends an OTP per
> login and rate-limits rapid repeats, so don't hammer the button. A wrong stored password is a
> lockout rather than an error, MTN especially.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **Fetch Statement** button doesn't appear | The selected Bank Account is in no feed's `accounts` list. Compare the exact record name including the ` - <bank>` suffix |
| `No bank feed is configured for Bank Account 'X'` | Same mismatch, thrown server-side by `trigger_fetch_for_account` when the client is stale |
| Click gives 500 | Wrong method path in the Client Script (verify with `frappe.get_attr`), or Redis/workers down (`bench doctor`) |
| Toast: `401 Unauthorized` from the service | `bank_feed_service_token` differs from the service's `BANK_FEED_SERVICE_TOKEN`; restart both sides after editing |
| Toast: `500` from the service | The scraper itself failed; check that project's logs / `journalctl -u <svc>` |
| Toast says done but nothing imported | The service returned no `created` count. Check the scraper's own log before assuming the statement was empty |
| Job queued but never finishes | Workers not running; check `bench doctor` / `supervisorctl status` |
| No toast at all | The import may still have worked; check the socketio process |
| `Connection refused` | The bank's service isn't running; `curl http://127.0.0.1:889X/health` |
| Login fails right after a password change | The service syncs credentials before each fetch, so this points at the stored value, not the sync. See [Bank credentials](bank-credentials.md) |

Errors from the enqueued job land in Desk → **Error Log**.

> **Reconciliation gotcha:** the Bank Reconciliation Tool needs Bank Transaction records *and*
> a populated **Company Bank Account** field on the Payment Entry. The GL account field alone
> is not enough for Auto Reconcile to match.
