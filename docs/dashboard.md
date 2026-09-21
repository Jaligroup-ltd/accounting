# Dashboard

> Part of **IAS**. See the [README](../README.md) for the module map, the role
> hierarchy and the conventions every feature here assumes.

**AR ageing chart.** `dashboard.py` exposes the whitelisted `get_ar_ageing`, which buckets
outstanding receivables into Current / 1-30 / 31-60 / 61-90 / 90+ by calling ERPNext's own
`accounts_receivable` report rather than querying the GL directly. It returns
`{labels, datasets}`, so a Dashboard Chart with Source = `Custom` renders it as-is. Falls back
to the user's default Company when none is passed.

The labels map `range1` to Current, `range2` to 1-30 and so on, which assumes the report's
default `range1=30` means "0-30 days". If those ranges are ever re-tuned, the labels must move
with them.

**Company selector.** `dashboard_company.py` holds the setter:

```
jalipartners.dashboard_company.set_dashboard_company
```

The selector itself is a **Custom HTML Block** (`filter_home_by_company`), a DB record edited
at `/app/custom-html-block`, dropped onto the top of the Home workspace, and persisted through
migrate via `fixtures` in `hooks.py`:

```python
fixtures = [
    {"doctype": "Custom HTML Block", "filters": {"name": ["in", ["filter_home_by_company"]]}},
]
```

Its script writes the user default that standard Number Cards already read, which is why no
card edits were needed; standard cards have locked filters and can't be edited directly. Two
consequences worth knowing:

- Setting the user's default Company also changes what's pre-filled on **new documents**
  (invoices, payments). For an admin switching context that's usually desirable, but it's a
  real change, not a view-only filter.
- Any card or chart that doesn't filter on `get_user_default("Company")` won't follow the
  selector. If one doesn't update, check that widget individually.

Re-export after UI edits: `bench --site accounting.jalikoi.rw export-fixtures`, then commit the
generated JSON.
