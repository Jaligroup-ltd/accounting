
import os
import re

import frappe
import requests
from frappe import _
from frappe.utils import flt

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(frappe.utils.get_bench_path(), ".env"))
except ImportError:
    pass  # fall back to real environment variables

# Huza itemTyCd -> ERPNext Item Group
ITEM_GROUP_BY_TYPE = {"1": "Raw Material", "2": "Products", "3": "Services"}


def _cfg(name, default=None):
    value = os.environ.get(name, default)
    if not value:
        frappe.throw(_("{0} is not configured").format(name))
    return value


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

@frappe.whitelist()
def sync_items_from_huza():
    frappe.has_permission("Item", "create", throw=True)
    frappe.enqueue(
        "jalipartners.huza_sync.run_item_sync",
        queue="long",
        timeout=1800,
        user=frappe.session.user,
    )
    return {"queued": True}


def run_item_sync(user):
    result = {"created": 0, "updated": 0, "failed": 0, "missing_tax_templates": []}
    try:
        tax_map = build_tax_map()
        for row in fetch_huza_items():
            code = row.get("itemCd")
            try:
                created = upsert_item(row, result, tax_map)
                upsert_price(row)
                frappe.db.commit()
                result["created" if created else "updated"] += 1
            except Exception:
                frappe.db.rollback()
                result["failed"] += 1
                frappe.log_error(frappe.get_traceback(), f"Huza item sync failed: {code}")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Huza item sync aborted")
        result["aborted"] = True
    result["missing_tax_templates"] = sorted(set(result["missing_tax_templates"]))
    frappe.publish_realtime("huza_item_sync_done", result, user=user)


# ---------------------------------------------------------------------------
# Huza API
# ---------------------------------------------------------------------------

def fetch_huza_items():
    r = requests.get(
        f"{_cfg('HUZA_BASE_URL').rstrip('/')}/items/getAllItems",
        headers={
            "Authorization": f"Bearer {_cfg('HUZA_API_TOKEN')}",
            "Accept": "application/json",
        },
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "Success":
        frappe.throw(_("Huza returned: {0}").format(body.get("message") or body.get("status")))
    return (body.get("data") or {}).get("items") or []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_uom(code):
    """UOM name is the EBM code itself, so the invoice step can read it back as-is.
    Do not rename these UOMs."""
    if code and not frappe.db.exists("UOM", code):
        frappe.get_doc({"doctype": "UOM", "uom_name": code, "enabled": 1}).insert(
            ignore_permissions=True
        )
    return code


def build_tax_map():
    """Return ({'A': ['A-Exempt - XD', ...], 'B': [...]}, {all EBM template names}).

    The code is the capital letter before the first '-' in the template TITLE
    (A-Exempt, B-Tax, C-Export, D-Non VAT). We match on title, never on name,
    because the name carries a company suffix (e.g. 'A-Exempt - XD')."""
    by_code, all_ebm = {}, set()
    for t in frappe.get_all(
        "Item Tax Template", filters={"disabled": 0}, fields=["name", "title"]
    ):
        m = re.match(r"^([A-Z])\s*-", t.title or "")
        if m:
            by_code.setdefault(m.group(1), []).append(t.name)
            all_ebm.add(t.name)
    return by_code, all_ebm


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------

def upsert_item(row, result, tax_map):
    by_code, all_ebm = tax_map
    code = row["itemCd"]
    exists = frappe.db.exists("Item", code)
    item = frappe.get_doc("Item", code) if exists else frappe.new_doc("Item")

    ty = str(row.get("itemTyCd") or "")
    group = ITEM_GROUP_BY_TYPE.get(ty, "Products")
    if not frappe.db.exists("Item Group", group):
        group = "Products"

    country = None
    if row.get("orgnNatCd"):
        country = frappe.db.get_value(
            "Country", {"code": row["orgnNatCd"].lower()}, "name"
        )

    ensure_uom(row.get("pkgUnitCd"))
    qty_uom = ensure_uom(row.get("qtyUnitCd")) or "Nos"

    item.update({
        "item_code": code,
        "item_name": row.get("itemNm"),
        "description": row.get("itemStdNm") or row.get("itemNm"),
        "item_group": group,
        "is_sales_item": 1,
        "is_purchase_item": 1,
        "disabled": 1 if (row.get("useYn") == "N" or row.get("deleted_at")) else 0,
        "country_of_origin": country,
        "safety_stock": flt(row.get("sftyQty")),
        "standard_rate": flt(row.get("dftPrc")),
    })

    if not exists:
        # ERPNext blocks changing these once stock transactions exist,
        # so they are only set on create.
        item.stock_uom = qty_uom
        item.is_stock_item = 0 if ty == "3" else 1

    if row.get("bcd") and not any(
        b.barcode == row["bcd"] for b in item.get("barcodes") or []
    ):
        item.append("barcodes", {"barcode": row["bcd"]})

    # Drop old EBM tax rows (whatever their tax_category), keep manually added
    # ones, then re-add the templates for this item's Huza tax code.
    item.set(
        "taxes",
        [t for t in item.get("taxes") or [] if t.item_tax_template not in all_ebm],
    )
    tax_code = row.get("taxTyCd")
    if tax_code:
        templates = by_code.get(tax_code)
        if templates:
            for name in templates:
                # tax_category intentionally left blank, otherwise the template
                # only applies when the transaction's tax category matches
                item.append("taxes", {"item_tax_template": name})
        else:
            result["missing_tax_templates"].append(tax_code)

    item.flags.ignore_permissions = True
    item.save() if exists else item.insert()
    return not exists


def upsert_price(row):
    price = flt(row.get("dftPrc"))
    if not price:
        return
    plist = _cfg("HUZA_PRICE_LIST", "Standard Selling")
    name = frappe.db.get_value(
        "Item Price", {"item_code": row["itemCd"], "price_list": plist}, "name"
    )
    doc = frappe.get_doc("Item Price", name) if name else frappe.new_doc("Item Price")
    doc.update({
        "item_code": row["itemCd"],
        "price_list": plist,
        "price_list_rate": price,
        "currency": frappe.defaults.get_global_default("currency"),
        "selling": 1,
    })
    doc.flags.ignore_permissions = True
    doc.save() if name else doc.insert()