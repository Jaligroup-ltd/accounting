# Bank credentials

> Part of **IAS**. See the [README](../README.md) for the module map, the role
> hierarchy and the conventions every feature here assumes.

The bank portal and mailbox logins the scrapers use are managed **in IAS**, not only in the
automation project's `.env`. The scraper services pull them over the API at startup and again
before every fetch, and fall back to a local cache and then to `.env` whenever IAS is
unreachable.

```
Bank Credential (Single doctype, passwords encrypted in __Auth)
     |
     |  GET /api/method/jalipartners.bank_credentials_api.get_credentials
     |  Authorization: token <api_key>:<api_secret>
     v
credentials.py  ->  os.environ  ->  .env + .credentials_cache.json
     |
     +-> service.py / bk_service.py / mtn_service.py   (startup + per fetch)
     +-> imbank.py / bkbank.py / mtnbank.py            (get_credential)
```

**Resolution order: IAS, then local cache, then `.env`.** A blank field is omitted from the API
response entirely rather than returned empty, so it never overwrites a working `.env` value.
That is what lets banks be migrated onto this one at a time.

Only the IAS half is documented here. The `credentials.py` client, the CLI, the `.env` settings
and the service hooks live in the `bank_feed_automation` project's own reference. For the
finance team there is a separate [*Bank Credentials User Guide*](https://docs.google.com/document/d/1hCf2giGqqieqH6fpnwqYmqMuI9yMBQo8ru1kPSwTuLI/edit?tab=t.0); if the form, the button or the
timing changes, that guide changes too.

## The DocType

`Bank Credential`, a **Single** doctype: one form, no list, stable URL at `/app/bank-credential`.

| Field | Type | Becomes |
|---|---|---|
| `imbank_username` | Data | `IMBANK_USERNAME` |
| `imbank_password` | **Password** | `IMBANK_PASSWORD` |
| `bk_username` | Data | `BK_USERNAME` |
| `bk_password` | **Password** | `BK_PASSWORD` |
| `zoho_imap_username` | Data | `ZOHO_IMAP_USERNAME` |
| `zoho_imap_password` | **Password** | `ZOHO_IMAP_PASSWORD` |
| `mtn_username` | Data | `MTN_USERNAME` |
| `mtn_password` | **Password** | `MTN_PASSWORD` |

> Password fields **must** be fieldtype `Password`. Frappe then encrypts the value into the
> `__Auth` table with the site's `encryption_key` and the form shows dots. As `Data` the
> password sits in plaintext in the database, readable by anyone with DB access or Report
> permission.

The API does not hard-code that list. It reads the DocType meta and treats a field as a
credential when the fieldtype is `Password`, or the fieldtype is `Data` and the fieldname ends
in `username`, `user`, `password`, `passwd`, `pass`, `secret` or `login` (case-insensitive).
Fieldnames are upper-cased to give the variable name. Housekeeping fields (`label`, `notes`,
`naming_series`) do not match and are ignored.

> **This DocType was created through the UI, so it lives in the database, not in this repo.**
> With developer mode off, Frappe stores it as a Custom DocType instead of writing files under
> the app. A fresh clone plus `bench migrate` will therefore *not* reproduce it, which is the
> one rule this app otherwise never breaks. Two ways to close that:
>
> - **Recreate it in the app** with `developer_mode` on locally, so the DocType is written as
>   files under `apps/jalipartners/jalipartners/<module>/doctype/bank_credential/` and ships
>   with the code. Cleanest, and consistent with everything else here.
> - **Export it as a fixture** and commit the JSON:
>
>   ```python
>   fixtures = [
>       {"doctype": "DocType", "filters": {"name": ["in", ["Bank Credential"]]}},
>       {"doctype": "Role", "filters": {"name": ["in", ["Bank Credential Manager"]]}},
>   ]
>   ```
>
>   then `bench --site accounting.jalikoi.rw export-fixtures`. Check where the permission rows
>   actually landed before trusting this: for a Custom DocType they normally ride along in the
>   DocType's own `permissions` child table, but anything set through Role Permission Manager
>   goes to `Custom DocPerm` and needs its own fixture entry.
>
> Either way the **stored values are not exported and must not be**. The `__Auth` rows stay on
> the site they were entered on, which is correct: credentials are not version-controlled.

## Permissions

Permission Rules carry **`Bank Credential Manager`** with Select, Read, Write and Create only.
Leave Delete, Export, Report, Print, Email and Share unticked: Export and Report are both
routes to bulk-reading the values. **Remove the `System Manager` row the UI adds by default**,
or every System Manager can read bank passwords.

`Bank Credential Manager` is a **Role, not a Role Profile.** Frappe permissions attach to roles;
a Role Profile is only a bundle. Add the role to the Super Admin Role Profile, then confirm it
is ticked on the individual User record, which is the source of truth.

## The API

Three whitelisted methods in `jalipartners.bank_credentials_api`:

| Method | Returns |
|---|---|
| `ping` | Auth check plus a field-discovery report: `is_single`, `matched`, `skipped` |
| `get_credentials` | `{"ok": true, "values": {"IMBANK_USERNAME": "...", ...}}`, blanks omitted |
| `get_fingerprints` | The same keys with SHA-256 prefixes instead of values, safe to log |

Authentication is a dedicated IAS user with an API key/secret pair:

- User `bank-feed-service@jalikoi.rw`, User Type = System User
- Roles: `Bank Credential Manager` only
- API Access, generate keys (the secret is shown once)

> There is deliberately **no `allow_guest` endpoint**. The site answers on the public internet,
> and an endpoint returning bank passwords behind nothing but a shared header token would be one
> leaked string away from disaster. The key/secret plus the IP restriction means even a leaked
> key is unusable off-box. Never commit either: they belong in the automation project's `.env`
> and nowhere else, not in a docstring, not in a comment.

## The button

**Accounting → Bank Statement Import** carries a **Configure Bank Credentials** button in the
list toolbar, added by a Client Script with Apply To = **List**. Client Scripts live in the
database, so this one is created per site rather than shipping with the repo.

It resolves the target at click time rather than hardcoding a URL, so a hash-named or recreated
record still works: a Single routes straight to the form, otherwise one record opens directly,
none opens a new form, and several open the list. Visibility keys off
`frappe.boot.user.can_read`, which reflects the real DocType permission. That only hides a
button that would error anyway; the server enforces access regardless.

## Adding a bank

1. Add `<bank>_username` (Data) and `<bank>_password` (Password) to the DocType. The API picks
   them up automatically, no code change.
2. Add one line to `CREDENTIAL_MAP` in `credentials.py` in the automation project.
3. Use `get_credential("<feed_key>")` in the new scraper.

`python credentials.py --ping` confirms the new fields were discovered.

Current feed keys: `imbank`, `bk`, `mtnmomo`, `zoho`, and optionally `mtn_zoho` for a dedicated
MTN mailbox.

## Security notes

**Back up `encryption_key`.** Frappe encrypts Password fields with the `encryption_key` from
`site_config.json`. Restore the database without it and every stored password is unrecoverable.
It belongs wherever the other production secrets live, not only on the server.

**File permissions.** `.env` and `.credentials_cache.json` are `frappe:frappe`, mode 0600.
`credentials.py` enforces the mode on every write but cannot fix ownership, so if `.env` is
edited as root, `chown frappe:frappe` afterwards or the next sync silently fails to persist.

**A wrong password is a lockout, not an error.** MTN especially, which is why
`MTN_MAX_FRESH_RESTARTS=0` exists. Editing a password is now a form field instead of SSH
access, so the barrier is far lower. Whoever holds the role should know what a typo costs.

## Troubleshooting (IAS side)

| Symptom | Cause / fix |
|---|---|
| HTTP 417, "Failed to get method ... is not a package" | The API module is not where `ERP_CREDENTIALS_METHOD` points. Put `bank_credentials_api.py` beside `bank_feed_api.py`; an `api.py` *file* cannot hold submodules |
| `/app/bank-credential` returns "not available" | The DocType is not on this site. It is a UI-created record, so it does not arrive with a `git pull`: import the fixture or recreate it |
| `matched: []` in the ping report | No field matched the discovery rules. Check fieldnames end in a credential word and the types are Data/Password |
| `no field for: X` in the ping report | A variable in `CREDENTIAL_MAP` has no DocType field. Add it, or accept it if optional (`MTN_ZOHO_*`) |
| `TableMissingError` on `('DocType', 'Bank Credential')` | The Client Script queried a list for a Single. Use the current script, which routes Singles straight to the form |
| Button missing from the list view | Client Script has Apply To = Form, or assets are cached. Set Apply To = List, `bench clear-cache`, hard reload |
| Values blank after converting to Single | Singles store in `tabSingles`, and `__Auth` rows keyed to the old record name are orphaned. Re-enter every value and save |
| Sync reports `source: env` or `source: cache` | IAS was unreachable. Check it against deploy times before calling it an incident |

Diagnostics that do not print secrets:

```bash
python credentials.py --ping      # auth, discovery, field types
python credentials.py --status    # usernames and password_set booleans
bench --site accounting.jalikoi.rw execute jalipartners.bank_credentials_api.ping
```

The last one bypasses HTTP entirely, which separates "the code is wrong" from "the transport is
wrong".

> **Deploy window.** The fallback's real job is covering `bench restart` and `bench migrate`.
> With both halves on one server, network failure is close to impossible, but IAS is briefly
> unavailable during every deploy. Keep `FEED_RUN_TIME` away from the deploy window.
