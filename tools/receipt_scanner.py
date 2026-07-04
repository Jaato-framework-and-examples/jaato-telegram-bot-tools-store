import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

TOOL_SCHEMA = {
    "name": "receipt_scanner",
    "description": (
        "Scans supermarket receipt images, extracts product and store information, "
        "and stores it in a database for later querying. "
        "Actions: scan (legacy OCR placeholder), store (accepts pre-extracted data "
        "from the assistant's vision read), reclassify, add_item (append item to existing receipt), query, stats, list, categories, export."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["scan", "store", "reclassify", "add_item", "query", "stats", "list", "categories", "export"],
                "description": "The action to perform."
            },
            "image_path": {
                "type": "string",
                "description": "Path to the receipt image file for 'scan' action."
            },
            "query": {
                "type": "string",
                "description": "SQL-like query string for 'query' action."
            },
            "category_name": {
                "type": "string",
                "description": "Name of the category to add/edit for 'categories' action."
            },
            "product_name": {
                "type": "string",
                "description": "Product name for certain queries."
            },
            "start_date": {
                "type": "string",
                "description": "Start date (YYYY-MM-DD) for time-based queries."
            },
            "end_date": {
                "type": "string",
                "description": "End date (YYYY-MM-DD) for time-based queries."
            },
            "supermarket": {
                "type": "string",
                "description": "Supermarket name for 'store' action."
            },
            "date": {
                "type": "string",
                "description": "Receipt date YYYY-MM-DD for 'store' action."
            },
            "total": {
                "type": "number",
                "description": "Receipt total amount for 'store' action."
            },
            "items": {
                "type": "string",
                "description": (
                    "JSON array of items for 'store' action. Each item: "
                    '{"name":"...","quantity":1.0,"unit":"ud","unit_price":1.0,'
                    '"total_price":1.0,"category":"..."}'
                ),
            },
        },
        "required": ["action"]
    },
}

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "receipt_scanner_data"
DB_PATH = DATA_DIR / "receipts.db"


def _init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS supermarkets (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY, name TEXT,
            normalized_name TEXT UNIQUE, category TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY, supermarket_id INTEGER,
            date TEXT, total_amount REAL, image_path TEXT,
            FOREIGN KEY(supermarket_id) REFERENCES supermarkets(id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY, receipt_id INTEGER,
            product_id INTEGER, quantity REAL, unit TEXT,
            unit_price REAL, total_price REAL,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        )""")
        conn.commit()


def _insert_supermarket(name: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO supermarkets (name) VALUES (?)", (name,))
        c.execute("SELECT id FROM supermarkets WHERE name = ?", (name,))
        sid = c.fetchone()[0]
        conn.commit()
    return sid


def _insert_product(name: str, normalized_name: str, category: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO products (name, normalized_name, category) "
            "VALUES (?, ?, ?)", (name, normalized_name, category))
        c.execute(
            "SELECT id FROM products WHERE normalized_name = ?",
            (normalized_name,))
        pid = c.fetchone()[0]
        conn.commit()
    return pid


def _insert_receipt(supermarket_id: int, date: str, total_amount: float,
                    image_path: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO receipts (supermarket_id, date, total_amount, image_path) "
            "VALUES (?, ?, ?, ?)",
            (supermarket_id, date, total_amount, image_path))
        rid = c.lastrowid
        conn.commit()
    return rid


def _insert_receipt_item(receipt_id: int, product_id: int, quantity: float,
                         unit: str, unit_price: float, total_price: float):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO receipt_items "
            "(receipt_id, product_id, quantity, unit, unit_price, total_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (receipt_id, product_id, quantity, unit, unit_price, total_price))
        conn.commit()


async def execute(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    action = args["action"]
    _init_db()

    # --- STORE: accept pre-extracted data from the assistant ---
    if action == "store":
        supermarket = args.get("supermarket")
        date = args.get("date")
        total = args.get("total")
        items_raw = args.get("items")
        image_path = args.get("image_path", "")

        if not supermarket or not date or total is None or not items_raw:
            return {"error": (
                "'store' requires: supermarket, date, total, items (JSON array)."
            )}

        try:
            items = json.loads(items_raw)
        except (json.JSONDecodeError, TypeError) as e:
            return {"error": f"Invalid items JSON: {e}"}

        sid = _insert_supermarket(supermarket)
        rid = _insert_receipt(sid, date, float(total), image_path)

        stored = 0
        for it in items:
            name = it.get("name", "Unknown")
            qty = it.get("quantity", 1.0)
            unit = it.get("unit", "ud")
            up = it.get("unit_price", it.get("total_price", 0))
            tp = it.get("total_price", 0)
            cat = it.get("category", "General")
            norm = name.lower().strip()
            pid = _insert_product(name, norm, cat)
            _insert_receipt_item(rid, pid, float(qty), unit, float(up), float(tp))
            stored += 1

        return {"result": (
            f"Receipt #{rid} from {supermarket} on {date} stored.\n"
            f"  Items stored: {stored}\n"
            f"  Total: {float(total):.2f} EUR"
        )}

    # --- LIST: show all receipts ---
    elif action == "list":
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT r.id, s.name, r.date, r.total_amount "
                "FROM receipts r JOIN supermarkets s ON r.supermarket_id = s.id "
                "ORDER BY r.date DESC")
            rows = c.fetchall()
        if not rows:
            return {"result": "No receipts stored yet."}
        lines = ["Receipts:"]
        for rid, sname, date, total in rows:
            lines.append(
                f"  #{rid} | {sname} | {date} | {total:.2f} EUR")
        return {"result": "\n".join(lines)}

    # --- QUERY: search products/items ---
    elif action == "query":
        product_name = args.get("product_name", "")
        start = args.get("start_date")
        end = args.get("end_date")
        cat = args.get("category_name")

        conditions = []
        params = []
        if product_name:
            conditions.append(
                "p.normalized_name LIKE ?")
            params.append(f"%{product_name.lower()}%")
        if start:
            conditions.append("r.date >= ?")
            params.append(start)
        if end:
            conditions.append("r.date <= ?")
            params.append(end)
        if cat:
            conditions.append("p.category = ?")
            params.append(cat)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT s.name, r.date, p.name, ri.quantity, ri.unit, "
                f"ri.unit_price, ri.total_price, p.category "
                f"FROM receipt_items ri "
                f"JOIN receipts r ON ri.receipt_id = r.id "
                f"JOIN supermarkets s ON r.supermarket_id = s.id "
                f"JOIN products p ON ri.product_id = p.id "
                f"{where} ORDER BY r.date DESC", params)
            rows = c.fetchall()

        if not rows:
            return {"result": "No matching items found."}
        lines = []
        for sname, date, pname, qty, unit, up, tp, cat in rows:
            lines.append(
                f"  {date} | {sname} | {pname} | "
                f"{qty}{unit} x {up:.2f} = {tp:.2f} EUR [{cat}]")
        return {"result": f"Found {len(rows)} items:\n" + "\n".join(lines)}

    # --- STATS: spending summary ---
    elif action == "stats":
        start = args.get("start_date")
        end = args.get("end_date")

        conditions = []
        params = []
        if start:
            conditions.append("r.date >= ?")
            params.append(start)
        if end:
            conditions.append("r.date <= ?")
            params.append(end)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT COUNT(*) FROM receipts r{where}", params)
            total_receipts = c.fetchone()[0]

            c.execute(
                f"SELECT COALESCE(SUM(r.total_amount), 0) "
                f"FROM receipts r{where}", params)
            total_spent = c.fetchone()[0]

            c.execute(
                f"SELECT p.category, SUM(ri.total_price), COUNT(*) "
                f"FROM receipt_items ri "
                f"JOIN receipts r ON ri.receipt_id = r.id "
                f"JOIN products p ON ri.product_id = p.id "
                f"{where} "
                f"GROUP BY p.category ORDER BY SUM(ri.total_price) DESC",
                params)
            cat_rows = c.fetchall()

        lines = [
            f"Total receipts: {total_receipts}",
            f"Total spent: {total_spent:.2f} EUR",
            "",
            "By category:"
        ]
        for cat, amount, count in cat_rows:
            lines.append(f"  {cat}: {amount:.2f} EUR ({count} items)")
        return {"result": "\n".join(lines)}

    # --- CATEGORIES: list or manage categories ---
    elif action == "categories":
        cat_name = args.get("category_name")
        if cat_name:
            # List products in a category
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT name, normalized_name FROM products "
                    "WHERE category = ? ORDER BY name", (cat_name,))
                rows = c.fetchall()
            if not rows:
                return {"result": f"No products in category '{cat_name}'."}
            lines = [f"Category: {cat_name} ({len(rows)} products)"]
            for name, norm in rows:
                lines.append(f"  - {name}")
            return {"result": "\n".join(lines)}
        else:
            # List all categories with counts
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT category, COUNT(*) FROM products "
                    "GROUP BY category ORDER BY COUNT(*) DESC")
                rows = c.fetchall()
            if not rows:
                return {"result": "No categories yet."}
            lines = ["Categories:"]
            for cat, count in rows:
                lines.append(f"  {cat}: {count} products")
            return {"result": "\n".join(lines)}

    # --- EXPORT: dump as JSON ---
    elif action == "export":
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            c.execute("SELECT * FROM supermarkets")
            supermarkets = [dict(r) for r in c.fetchall()]

            c.execute("SELECT * FROM products")
            products = [dict(r) for r in c.fetchall()]

            c.execute("SELECT * FROM receipts")
            receipts = [dict(r) for r in c.fetchall()]

            c.execute("SELECT * FROM receipt_items")
            items = [dict(r) for r in c.fetchall()]

        data = {
            "supermarkets": supermarkets,
            "products": products,
            "receipts": receipts,
            "receipt_items": items,
        }
        out_path = DATA_DIR / "export.json"
        out_path.write_text(json.dumps(data, indent=2, default=str))
        return {"result": (
            f"Exported to {out_path}\n"
            f"  Supermarkets: {len(supermarkets)}\n"
            f"  Products: {len(products)}\n"
            f"  Receipts: {len(receipts)}\n"
            f"  Items: {len(items)}"
        )}

    # --- RECLASSIFY: change category of a product ---
    elif action == "reclassify":
        product_name = args.get("product_name", "")
        new_cat = args.get("category_name", "")
        if not product_name or not new_cat:
            return {"error": "'reclassify' requires product_name and category_name."}
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE products SET category = ? WHERE normalized_name = ?",
                (new_cat, product_name.lower().strip()))
            changed = c.rowcount
            conn.commit()
        if changed:
            return {"result": f"Reclassified '{product_name}' -> '{new_cat}'."}
        return {"result": f"Product '{product_name}' not found (no change)."}

    # --- ADD_ITEM: append item to existing receipt ---
    elif action == "add_item":
        rid = args.get("receipt_id")
        item_raw = args.get("item")
        if not rid or not item_raw:
            return {"error": "'add_item' requires receipt_id and item (JSON object)."}
        try:
            it = json.loads(item_raw)
        except (json.JSONDecodeError, TypeError) as e:
            return {"error": f"Invalid item JSON: {e}"}
        name = it.get("name", "Unknown")
        norm = name.lower().strip()
        cat = it.get("category", "General")
        pid = _insert_product(name, norm, cat)
        _insert_receipt_item(
            rid, pid,
            float(it.get("quantity", 1.0)),
            it.get("unit", "ud"),
            float(it.get("unit_price", it.get("total_price", 0))),
            float(it.get("total_price", 0)))
        return {"result": f"Added '{name}' to receipt #{rid} [{cat}]."}

    # --- SCAN: legacy placeholder (no real OCR) ---
    elif action == "scan":
        return {"error": (
            "'scan' is deprecated. Use 'store' with pre-extracted data "
            "from the assistant's vision read instead."
        )}

    return {"error": f"Unknown action: {action}"}
