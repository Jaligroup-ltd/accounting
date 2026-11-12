# Huza EBM Integration (jalipartners app)

Developer documentation for the feature that connects ERPNext 15 to **Huza** (the EBM / RRA e-invoicing platform) from inside the `jalipartners` Frappe app. There is no separate middleware: all logic lives in the app.

- **Stack:** Frappe 15.x, ERPNext 15.x, Python 3.10, MariaDB
- **App:** `apps/jalipartners` (Python package `jalipartners`)
- **Features:**
  1. **Sync from Huza**: menu entry on the Item list that imports Huza items into ERPNext.
  2. **Generate EBM Invoice**: menu entry on a submitted Sales Invoice that registers the invoice in Huza and optionally sends the receipt link to the customer by SMS and email.

---

## 1. Architecture

```
Browser (Item list / Sales Invoice form)
        |  frappe.call (whitelisted methods)
        v
jalipartners (Frappe app, runs inside the bench)
   huza_sync.py   -----> Huza  GET  /items/getAllItems
   huza_ebm.py    -----> Huza  POST /invoices
   intouch_sms.py -----> Intouch SMS API
   frappe.sendmail ----> ERPNext outgoing Email Account
```

Design rules:

- Secrets (Huza token, SMS credentials) stay on the server in `.env`. The browser never sees them.
- The Huza invoice is the fiscal record. Anything that happens after Huza accepts the invoice (saving the number, SMS, email) must never make the invoice look failed, and must never cause the same invoice number to be reused.
- ERPNext is the source of truth for prices and tax **amounts on invoices**. Huza is the source of truth for EBM codes (classification, packaging, quantity unit, tax type, insurance fields).

---

## 2. File map

All paths are relative to `apps/jalipartners/jalipartners/`.

| File | Purpose |
|---|---|
| `huza_sync.py` | Item sync: Huza client, upserts for Item and Item Price, background job, `.env` loader |
| `huza_ebm.py` | EBM invoice generation: validation, payload builder, Huza call, notifications, cancel guard |
| `intouch_sms.py` | Intouch SMS client (`send_sms`) |
| `ebm_tax_setup.py` | CLI helpers: create EBM tax templates per company, verify what ERPNext picks for an item |
| `patches/add_ebm_fields_to_sales_invoice.py` | Creates the `custom_ebm_invoice_number` custom field |
| `patches.txt` | Registers the patch under `[post_model_sync]` |
| `public/js/item_list.js` | "Sync from Huza" menu entry (Item list) |
| `public/js/sales_invoice.js` | "Generate EBM Invoice" menu entry and dialog (Sales Invoice form) |
| `hooks.py` | Wires the JS files and the cancel guard |

### hooks.py entries

```python
doctype_js = {
    "Bank Reconciliation Tool": "public/js/cash_coding.js",   # pre-existing
    "Sales Invoice": "public/js/sales_invoice.js",
}

# NOTE: list views use doctype_list_js, NOT doctype_js
doctype_list_js = {
    "Item": "public/js/item_list.js",
}

doc_events = {
    "Sales Invoice": {
        "before_cancel": "jalipartners.huza_ebm.block_cancel_if_fiscalized",
    },
}
```

If these dicts already exist in `hooks.py`, add keys to the existing dicts. Defining a hook twice silently replaces the first definition.

---

## 3. Configuration (`.env`)

Location: the **bench root** (`frappe-bench/.env`, next to `apps/` and `sites/`). It is loaded by `huza_sync.py` with `python-dotenv` (`bench pip install python-dotenv`). Real environment variables also work.

```
HUZA_BASE_URL=https://<huza-host>/api
HUZA_API_TOKEN=<bearer token>
HUZA_PRICE_LIST="Standard Selling"

INTOUCH_SEND_SMS_URL=https://www.intouchsms.co.rw/api/sendsms/.json
INTOUCH_USERNAME=<username>
INTOUCH_PASSWORD="<password>"
INTOUCH_SENDER=<registered sender id>

# Optional: replace the host of the receipt URL returned by Huza
HUZA_RECEIPT_BASE_URL=https://<public-huza-host>
```

| Variable | Required | Notes |
|---|---|---|
| `HUZA_BASE_URL` | yes | Base of the Huza API. Must not point at ERPNext itself (port 8000 clash in dev). Include `/api` if Huza routes are under it. |
| `HUZA_API_TOKEN` | yes | Sent as `Authorization: Bearer <token>` |
| `HUZA_PRICE_LIST` | no | Price list that receives `dftPrc`. Defaults to `Standard Selling`. |
| `INTOUCH_*` | only when SMS is used | Checked before anything is sent to Huza when the SMS box is ticked |
| `HUZA_RECEIPT_BASE_URL` | no | Needed when Huza returns an internal URL such as `http://localhost:8080/...` |

Gotchas:

- **Quote values with spaces or special characters.** `bench start` runs through honcho, which reads `.env` itself and mangles unquoted values (`Standard Selling` became `StandardSelling`).
- **Restart after every change** (stop and start `bench start`, or restart supervisor). The web process and the background workers only read `.env` when they start.
- **Docker:** `.env` is not read from inside containers. Pass the same variables with `env_file:` / `environment:` on the backend, worker and scheduler services.
- `chmod 600 .env` and keep it out of git.

---

## 4. Data model change

One custom field on **Sales Invoice**, created by the patch:

| Field | Type | Flags |
|---|---|---|
| `custom_ebm_section` | Section Break (collapsible, after `remarks`) | |
| `custom_ebm_invoice_number` | Data | read only, **no copy**, allow on submit |

Purpose: remember that an invoice was already registered in Huza (idempotency), and show the number on the form. `no_copy` matters: Duplicate and Amend must not carry the number over.

The patch also deletes two fields from an earlier design (`custom_ebm_generated_at`, `custom_ebm_response`) if they exist. It is safe to run more than once.

Install and register:

```text
# patches.txt
[post_model_sync]
jalipartners.patches.add_ebm_fields_to_sales_invoice
```

```bash
bench --site <site> migrate
# or, immediately on one site:
bench --site <site> execute jalipartners.patches.add_ebm_fields_to_sales_invoice.execute
```

The invoice number counter is a standard Frappe naming series row (`tabSeries`, key `EBM-INV-`). No new doctype or table is created.

No custom fields are added to **Item**. EBM codes are re-read from Huza when an invoice is generated.

---

## 5. Feature A: Sync from Huza (Item list)

### Flow

1. `item_list.js` adds **Sync from Huza** as the first entry of the Item list `...` menu (it wraps any existing `onload`).
2. The entry calls `jalipartners.huza_sync.sync_items_from_huza` (whitelisted, requires Item create permission).
3. That method enqueues `run_item_sync` on the `long` queue (timeout 1800 s) and returns immediately.
4. The job calls `GET {HUZA_BASE_URL}/items/getAllItems` (Bearer token). Items are in `data.items`.
5. For each item: `upsert_item` then `upsert_price`, with one commit per item. A failure rolls back only that item and is logged as `Huza item sync failed: <itemCd>` in the Error Log.
6. The job publishes the realtime event `huza_item_sync_done` to the requesting user. The page shows a popup and refreshes the list.

Event payload:

```json
{ "created": 0, "updated": 0, "failed": 0, "missing_tax_templates": ["B"], "aborted": false }
```

The sync is an **upsert keyed on `itemCd`**, so it is safe to run repeatedly. It does not delete anything. Items with `useYn = "N"` or a `deleted_at` value are disabled.

### Field mapping

| Huza | ERPNext |
|---|---|
| `itemCd` | `item_code` (Item name). Stock Settings must have **Item Naming By = Item Code**. |
| `itemNm` | `item_name` |
| `itemStdNm` | `description` (falls back to `itemNm`) |
| `itemTyCd` | `item_group`: 1 Raw Material, 2 Products, 3 Services. Also `is_stock_item` (0 for type 3). `is_stock_item` is set **on create only**. |
| `qtyUnitCd` | `stock_uom`, set on create only. A UOM **named exactly like the code** is created if missing. Do not rename these UOMs. |
| `pkgUnitCd` | A UOM named like the code is created if missing. Not stored on the item. |
| `taxTyCd` | Item Tax Template rows (see section 6). |
| `dftPrc` | **Item Price** in `HUZA_PRICE_LIST` (`selling = 1`) and `standard_rate` on the Item |
| `bcd` | `barcodes` child row |
| `orgnNatCd` | `country_of_origin` (matched on the lowercase ISO code) |
| `sftyQty` | `safety_stock` |
| `useYn` / `deleted_at` | `disabled` |

Not stored: `itemClsCd`, `isrcc*`, `isrcRt`, `isrcAmt`, `external_id`, group prices `grpPrcL1..L5`, and the audit fields. `is_sales_item` and `is_purchase_item` are set to 1.

---

## 6. Tax setup (required before invoices work)

### Concept

Huza tax codes map to **Item Tax Templates**, matched on the template **title** (the capital letter before the first `-`). The template **name** gets a company suffix (`B-Tax - XD`), so never match on name.

| Code | Title | Rate |
|---|---|---|
| A | `A-Exempt` | 0 |
| B | `B-Tax` | 18 |
| C | `C-Export` | 0 |
| D | `D-Non VAT` | 0 |

- Item Tax Templates are **per company**. ERPNext only offers a template whose company equals the invoice's company. The sync attaches every enabled matching template (one per company) to each item.
- `tax_category` on the Item Tax rows is **deliberately left blank**. ERPNext only selects a row when the row's Tax Category equals the invoice's Tax Category, so a value like "B" would stop the template from auto-filling.
- The rate lives inside the template (Taxes table: VAT account + Tax Rate). For ERPNext to add the tax, the invoice also needs a **Sales Taxes and Charges** row for the same account. The item template then overrides the rate per line.

### Setting up a company

```bash
# 1. find the VAT account (Tax type liability account)
bench --site <site> execute frappe.get_all --kwargs '{"doctype": "Account", "filters": {"company": "<Company>", "account_type": "Tax", "is_group": 0}, "pluck": "name"}'

# 2. create/fix the four templates and an "EBM VAT" Sales Taxes and Charges template
bench --site <site> execute jalipartners.ebm_tax_setup.setup_ebm_tax_templates --kwargs '{"company": "<Company>", "vat_account": "<VAT account>"}'
```

`setup_ebm_tax_templates` replaces the tax rows of existing templates with the single VAT row and the rate above. The created "EBM VAT" row has a default rate of **0**, so only items whose template says 18 get tax. It becomes the company default only if the company has no default Sales Taxes and Charges template.

Then: run **Sync from Huza** again (so items pick up the new templates) and re-select the item on any existing invoice row.

### Verifying

```bash
bench --site <site> execute jalipartners.ebm_tax_setup.check_item_taxes --kwargs '{"company": "<Company>", "items": ["<itemCd>"]}'
```

Returns the item's tax rows and the template ERPNext would pick (`picks`). `null` means the invoice row will stay empty.

---

## 7. Feature B: Generate EBM Invoice (Sales Invoice)

### When the menu entry shows

On a Sales Invoice that is **submitted**, **not a return**, and has **no** `custom_ebm_invoice_number`. It is the first entry of the `...` menu. Once an EBM number exists, the entry disappears and a green banner shows the number.

### Dialog (`sales_invoice.js`)

The dialog always opens. Field values are prefilled from the Customer.

| Field | Shown for | Default | Rules |
|---|---|---|---|
| Customer TIN | Company customers | `Customer.tax_id` (digits only) | required, 9 digits |
| Purchase Code | Company customers | `Sales Invoice.po_no` | required, must not be `000000` |
| Customer Phone | everyone | `contact_mobile` or `Customer.mobile_no` | required (Huza rejects an empty phone), at least 9 digits |
| Customer Email | everyone | `contact_email` or `Customer.email_id` | required only if "Send by email" is ticked |
| Send by SMS | everyone | unchecked | uses SMS credits |
| Send by email | everyone | unchecked | |

"Company" means `Customer.customer_type == "Company"`. Individuals send purchase code `000000` and their TIN comes from `Customer.tax_id`, or the last 9 digits of the phone number when the Tax ID is empty.

### Server flow (`huza_ebm.generate_ebm_invoice`)

```
1. Check custom_ebm_invoice_number column exists
2. Lock the Sales Invoice row (SELECT ... FOR UPDATE)
3. Permission check ("submit"), then _validate:
     docstatus = 1, not a return, no EBM number yet, invoice currency = company currency
4. _resolve_party        -> phone, TIN, purchase code (throws on bad values)
5. _check_notifications  -> valid email / INTOUCH_* configured, BEFORE contacting Huza
6. Fetch all Huza items, build {itemCd: item}
7. invoice_number = next value of series EBM-INV-
8. _build_payload        -> validates items exist in Huza and totals reconcile
9. POST {HUZA_BASE_URL}/invoices
10. On success: commit, save custom_ebm_invoice_number, add timeline comment (with receipt link)
11. Send SMS / email (never raises), add timeline comment, commit
12. Return { invoice_number, notifications, receipt_link }
```

Anything that throws before step 9 rolls back, including the number taken in step 7, so no number is wasted.

### API reference

```python
@frappe.whitelist()
jalipartners.huza_sync.sync_items_from_huza() -> {"queued": True}

@frappe.whitelist()
jalipartners.huza_ebm.generate_ebm_invoice(
    sales_invoice, purchase_code=None, customer_tin=None,
    customer_phone=None, customer_email=None, send_sms=0, send_email=0,
) -> {
    "invoice_number": int,
    "notifications": {"sms": {"ok": bool, "error": str|None},     # only requested channels
                      "email": {"ok": bool, "error": str|None}},
    "receipt_link": str|None,
}
```

### Invoice numbering

`getseries("EBM-INV-", 1)` returns the next integer (atomic, row-locked). **Seed it before the first real invoice** with the highest `invoice_number` already used in Huza (other systems may also issue numbers there):

```python
# bench --site <site> console
frappe.db.sql("update `tabSeries` set current=%s where name='EBM-INV-'", 6722)  # or insert if the row is missing
frappe.db.commit()
```

---

## 8. Huza payload

`POST {HUZA_BASE_URL}/invoices`, `Authorization: Bearer <token>`, JSON body.

### Header fields

| Field | Value |
|---|---|
| `original_invoice_number` | `"0"` |
| `sender` | Sales Invoice company |
| `recipient` | `customer_name` |
| `recipient_phone_number` | dialog phone, normalized to `+250XXXXXXXXX` |
| `customer_tin` | see dialog rules |
| `purchase_code` | dialog value for companies, else `"000000"` |
| `sales_type_code` / `receipt_type_code` / `payment_type_code` / `invoice_status_code` | `"N"` / `"S"` / `"01"` / `"01"` |
| `validated_date` / `date` / `due_date` | now `YmdHis` / now `Ymd` / now + 7 days `Ymd` |
| `notes` / `terms` | `Notes for #<customer>` / `Terms & Conditions for #<customer>` |
| `subtotal`, `total`, `taxable_amount` | sum of inclusive line amounts |
| `tax` | sum of line tax amounts |
| `discount` | `"0"` (discounts are already inside ERPNext `net_amount`) |
| `amount_paid` / `balance_due` | see below |
| `registrant_*`, `modifier_*` | `"SYSTEM"` |
| `print_size` | `"A4"` |
| `report_number` | `random.randint(100000, 999999999)` |
| `invoice_number` | series value (integer) |

All money values are strings with two decimals.

### Item fields (taken from the Huza item, matched on `item_code == itemCd`)

`name` (`itemNm`), `item_classification_code` (`itemClsCd`), `packaging_unit_code` (`pkgUnitCd`), `uom` (`qtyUnitCd`), `item_code` (`itemCd`), `item_type_code` (`itemTyCd`), `tax_type` (`taxTyCd`), `bcd`, `isrcRt`, `isrcAmt`, `isrccNm`, `isrccCd`. Fixed: `package = "1"`, `discount_rate = discount_amount = "0"`.

If an invoice contains an item that does not exist in Huza, generation stops with the list of missing item codes.

### Tax computation (important)

RRA works on **tax-inclusive amounts**: the tax is computed from the inclusive amount. Reference: a B item priced 1,000.00 shows TOTAL TAX B = 152.54 (`1000 x 18 / 118`).

1. Per line, take ERPNext `net_amount`.
   - If the invoice has tax added on top (`total_taxes_and_charges > 0`), `gross = net * (1 + rate/100)`.
   - Otherwise `net_amount` is treated as already inclusive: `gross = net`.
   - `unit = round(gross / qty, 2)` and `gross = round(unit * qty, 2)`.
2. Per tax code, `group_tax = round(sum(gross) * rate / (100 + rate), 2)`. Line taxes are allocated proportionally and the rounding difference goes to the last line of the group.
3. Line `rate` = inclusive unit price, `amount` = `taxable_amount` = inclusive line amount, `tax_amount` = allocated tax.
4. Safety check: `|sum(gross) - doc.grand_total| <= 1`, otherwise generation stops with a clear message (usually a tax setup problem, see section 6).

Rates come from the constant `TAX_RATE = {"A": 0, "B": 18, "C": 0, "D": 0}` in `huza_ebm.py`. Verify against the official RRA code table.

`amount_paid` / `balance_due`: if `outstanding_amount < 0.5` the invoice is fully paid (`amount_paid = total`). Otherwise `amount_paid = max(0, payable - outstanding)` where `payable = rounded_total or grand_total`. `balance_due = total - amount_paid`.

### Response handling

- **Success:** HTTP < 400 and `status` is `true` (or `"Success"`). The receipt URL is in `data.file_path`.
- **Rejected:** logged in the Error Log as `Huza EBM rejected: <invoice>` with Huza's reply and the exact payload. The user sees Huza's message.
- **Timeout / connection error:** logged as `Huza EBM no response: <invoice>` with the payload. The invoice **may** be registered. The message gives the invoice number so the user can check Huza before retrying.

Errors seen during development:

| Response | Cause | Fix |
|---|---|---|
| 422 `recipient_phone_number` required | Customer without a phone | Phone is now mandatory in the dialog |
| `Wrong Amount computation` | Tax-exclusive amounts were sent | Send tax-inclusive amounts (see above) |

---

## 9. Notifications (SMS and email)

Run only after Huza accepted the invoice and the number was saved. They never raise: a failed notification is reported to the user (orange popup) and written to the invoice timeline, and the invoice stays registered.

The **receipt link** (`data.file_path`) is the content of both messages. If a notification is requested and Huza returned no link, it is reported as failed with "Huza did not return a receipt link".

**SMS** (`intouch_sms.send_sms`):

- `POST INTOUCH_SEND_SMS_URL`, multipart form: `recipients` (local format `07XXXXXXXX`), `sender`, `message`.
- Auth: HTTP Basic with `INTOUCH_USERNAME` / `INTOUCH_PASSWORD` (assumption based on the sample curl; adjust if Intouch expects form fields).
- Success: `success: true`. Failure: the error is read from `response[0].errors.error` (for example `Invalid Sender`).
- Text: `<Company>: invoice no. <n>, <currency> <total>. View: <link>`

**Email** (`frappe.sendmail`, `now=True`):

- Recipient: dialog email. Content: invoice number, total, a "View your invoice" button and the plain link.
- Requires an enabled **outgoing Email Account** in ERPNext. No PDF is attached (the ERPNext print is not the fiscal receipt).

---

## 10. Deployment checklist

1. Deploy the code, add the `.env` values, `bench pip install python-dotenv` if missing.
2. `bench --site <site> migrate` (runs the patch) and confirm:
   `frappe.db.has_column("Sales Invoice", "custom_ebm_invoice_number")` is `True`.
3. For each company that issues EBM invoices: run `setup_ebm_tax_templates` (section 6), then set the company's default Sales Taxes and Charges template.
4. `bench build --app jalipartners`, `bench --site <site> clear-cache`, restart the bench (web, workers, scheduler).
5. Run **Sync from Huza**, then check one item with `check_item_taxes`.
6. Seed the `EBM-INV-` counter (section 7).
7. Make sure a worker is running for the `long` queue (item sync) and an outgoing Email Account is configured (email).
8. Production: Huza must return a public receipt URL (or set `HUZA_RECEIPT_BASE_URL`), and `HUZA_BASE_URL` must use HTTPS.

---

## 11. Testing

1. Create a Sales Invoice for the company that has the EBM templates, using a **synced** item (one with the `... - <company>` template). The row's Item Tax Template should fill automatically, with VAT at 18% for a B item.
2. Submit it, open `...`, click **Generate EBM Invoice**, fill the dialog.
3. Expect: green alert, banner with the EBM number, timeline comments (generated with receipt link, SMS/email results).
4. Compare the invoice in Huza: totals match, tax on a B line equals `inclusive amount x 18 / 118`.
5. Negative tests: unsynced item, missing phone, company customer with purchase code `000000`, second click on the same invoice (must be refused), unreachable Huza (number must not be consumed on a rejection).
6. SMS in isolation: `from jalipartners.intouch_sms import send_sms; print(send_sms("+250...", "test"))` returns `(True, None)` on success.

---

## 12. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Menu entry missing on the Item list | Hook registered under `doctype_js` instead of `doctype_list_js` | Fix `hooks.py`, `bench build`, `clear-cache`, restart, hard refresh |
| Menu entry missing on a Sales Invoice | JS not registered, invoice not submitted, is a return, or already has an EBM number | Check `doctype_js`; check the browser console for errors |
| `No module named 'jalipartners.intouch_sms'` | File missing or in the wrong folder | It must be `jalipartners/jalipartners/intouch_sms.py` |
| `Unknown column 'custom_ebm_invoice_number'` | Patch not run | Run the patch (section 4). Do not click Generate again for an invoice Huza already accepted: record its number first. |
| `ModuleNotFoundError` for the patch | Patch file or `patches/__init__.py` missing | Create it at `jalipartners/patches/` |
| Item Tax Template empty on invoice rows | No template for the invoice's company, template disabled, or a Tax Category set on the item row | `check_item_taxes`; run `setup_ebm_tax_templates`; re-sync; re-select the item |
| `Could not find Price List: StandardSelling` | `.env` value not quoted | `HUZA_PRICE_LIST="Standard Selling"`, restart |
| `HUZA_BASE_URL is not configured` in the sync popup | Worker not restarted after editing `.env` | Restart the bench |
| Console shows old data or `Record has changed since last read` | The console keeps a stale DB snapshot | `frappe.db.rollback()` or open a new console |
| `EBM total X does not match the invoice total Y` | Tax setup mismatch (missing VAT row, wrong template, wrong tax code) | Fix the taxes on the invoice |
| SMS fails with `Invalid Sender` | `INTOUCH_SENDER` is not a registered sender id | Use the id registered with Intouch |
| Email fails | No outgoing Email Account | Configure one in ERPNext |
| Customers get a `localhost` link | Huza returns its internal URL | Fix Huza's public URL or set `HUZA_RECEIPT_BASE_URL` |

Where to look: **Error Log** (titles `Huza EBM rejected`, `Huza EBM no response`, `Huza item sync failed`, `Intouch SMS rejected`, `EBM notification failed`), `frappe-bench/logs/worker.log` and `worker.error.log`, and the Sales Invoice timeline.

---

## 13. Security notes

- Keep `.env` out of git and readable only by the service user. Rotate the Huza token and SMS password periodically.
- Generation requires the **submit** permission on Sales Invoice and takes a row lock, so concurrent clicks cannot register the same invoice twice.
- Error Log entries for Huza calls contain the full payload (customer name, TIN, phone). Restrict access to the Error Log doctype accordingly.
- Receipt URLs are links to PDFs that anyone holding the link may open. Treat them as sensitive and prefer unguessable file names on the Huza side.
- Use HTTPS for Huza and Intouch in production.
- An invoice with an EBM number cannot be cancelled (`before_cancel` guard).

---

## 14. Known limitations and open items

- **Credit notes / returns** are not supported (the menu entry is hidden for returns).
- **Payment Entry** trigger is not implemented. The feature works at Sales Invoice level.
- **Suppliers / Purchase Invoices** are not covered.
- **Lost response recovery** is manual. After a timeout there is no automatic "query Huza before retrying".
- **Number collisions:** `invoice_number` and `report_number` are generated by us. The counter must be seeded above any number issued elsewhere, and `report_number` is random (collision is unlikely but not impossible).
- **Tax rates** are constants and must be checked against the RRA tables. Tax category per item cannot differ between companies.
- **Intouch authentication** (HTTP Basic) is an assumption.
- **Item sync** reads the full Huza item list each time (no pagination or caching) and never deletes items.
- **Huza receipt data** (SDC id, signature) is not stored in ERPNext. Only the number and the link (timeline) are kept.
- **Multi-currency** invoices are refused (company currency only).
- Business decision pending for each company: whether prices are tax-inclusive. With the "EBM VAT" template, ERPNext adds VAT on top of the item price. To sell at the inclusive price, tick **Is this Tax included in Basic Rate?** on the VAT row of that template. The code handles both cases.
