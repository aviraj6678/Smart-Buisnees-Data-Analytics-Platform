"""
data/generate_sample.py
-----------------------
Generate a synthetic sample dataset for the Smart Business Data Analytics Platform.

Output: data/sample_data.csv

Dataset properties
------------------
- 700-900 transaction rows (line items)
- Jan 2023 - Dec 2023 (12 months)
- 5 product categories, 4 regions, 55 customers, 35 products
- Multi-product orders: each order contains 1-4 line items
  => COUNT(DISTINCT order_id) will be significantly less than total rows
- Deliberate anomalies for insights demo:
    * 2 products with negative margin (cost > price)
    * September 2023 has ~30% revenue drop vs August (revenue decline detector)
    * Top customer holds ~25% of total revenue (concentration warning)

All data is synthetic. Run this script to regenerate:
    python data/generate_sample.py
"""

from __future__ import annotations

import pathlib
import numpy as np
import pandas as pd

# ── Reproducible seed ─────────────────────────────────────────────────────────
RNG = np.random.default_rng(seed=42)

# ── Catalogue ──────────────────────────────────────────────────────────────────
REGIONS = ["North", "South", "East", "West"]

PRODUCTS = [
    # (name, category, unit_price, unit_cost)  — cost < price = healthy margin
    # Electronics
    ("Laptop Pro",       "Electronics",  1200.00,  780.00),
    ("Wireless Keyboard","Electronics",    89.00,   45.00),
    ("USB-C Hub",        "Electronics",    49.00,   22.00),
    ("Monitor 24in",     "Electronics",   350.00,  210.00),
    ("Webcam HD",        "Electronics",    75.00,   38.00),
    ("Noise Headphones", "Electronics",   199.00,  110.00),
    ("Smart Speaker",    "Electronics",   129.00,   72.00),
    # Office Supplies
    ("Ergonomic Chair",  "Office Supplies",  320.00, 175.00),
    ("Standing Desk",    "Office Supplies",  580.00, 340.00),
    ("Desk Lamp LED",    "Office Supplies",   45.00,  22.00),
    ("Whiteboard 4ft",   "Office Supplies",   95.00,  52.00),
    ("Printer Ink Set",  "Office Supplies",   38.00,  18.00),
    ("File Cabinet",     "Office Supplies",  145.00,  88.00),
    # Software
    ("CRM License",      "Software",   250.00, 120.00),
    ("Analytics Suite",  "Software",   450.00, 210.00),
    ("Project Mgmt Tool","Software",   180.00,  85.00),
    ("Security Suite",   "Software",   120.00,  55.00),
    ("Cloud Storage 1TB","Software",    60.00,  28.00),
    # Peripherals
    ("Mechanical Keyboard","Peripherals",  110.00,  62.00),
    ("Gaming Mouse",     "Peripherals",    65.00,   32.00),
    ("Trackpad Pro",     "Peripherals",    89.00,   48.00),
    ("Docking Station",  "Peripherals",   180.00,  105.00),
    ("LED Strip Kit",    "Peripherals",    35.00,   18.00),
    ("Power Bank 20K",   "Peripherals",    55.00,   28.00),
    # Accessories
    ("Laptop Bag",       "Accessories",    65.00,   30.00),
    ("Screen Cleaner Kit","Accessories",   12.00,    5.00),
    ("Cable Organiser",  "Accessories",    18.00,    8.00),
    ("Monitor Arm",      "Accessories",    85.00,   45.00),
    ("Wrist Rest",       "Accessories",    22.00,   10.00),
    ("Privacy Screen",   "Accessories",    55.00,   28.00),
    # Deliberate negative-margin products (cost > price)
    ("Clearance Tablet", "Electronics",    89.00,  110.00),   # loss maker
    ("Promo USB Drive",  "Accessories",     4.00,    6.50),   # loss maker
    # Deliberate near-zero-margin product
    ("Basic Mouse",      "Peripherals",    15.00,   14.50),   # ~3% margin
    ("Cheap HDMI Cable", "Accessories",     8.00,    7.80),   # ~2.5% margin
    ("Budget Headset",   "Electronics",    25.00,   24.50),   # ~2% margin
]

# 55 customers
CUSTOMERS = [(f"CUST-{i:03d}", f"Customer {i:03d}") for i in range(1, 56)]

# Weight the first customer heavily for concentration insight
CUSTOMER_WEIGHTS = np.array(
    [20.0] + [1.0] * 54,   # Customer 001 gets 20x weight
    dtype=float,
)
CUSTOMER_WEIGHTS = CUSTOMER_WEIGHTS / CUSTOMER_WEIGHTS.sum()

# Product weights — normal products ordered more; loss makers ordered rarely
PRODUCT_WEIGHTS = np.array(
    [1.0] * 30 + [0.3, 0.3] + [0.6, 0.6, 0.6],   # loss makers + near-zero
    dtype=float,
)
PRODUCT_WEIGHTS = PRODUCT_WEIGHTS / PRODUCT_WEIGHTS.sum()


def _month_order_count(month: int) -> int:
    """
    Return the number of orders to generate for a given month (1-12).
    September (month 9) gets ~30% fewer orders to create the revenue decline.
    """
    base = RNG.integers(30, 50)   # 30-49 orders per month normally
    if month == 9:
        base = int(base * 0.68)   # ~32% drop
    return int(base)


def generate() -> pd.DataFrame:
    rows = []
    txn_counter = 1
    order_counter = 1

    for month in range(1, 13):   # Jan-Dec 2023
        n_orders = _month_order_count(month)

        for _ in range(n_orders):
            order_id = f"ORD-{order_counter:05d}"
            order_counter += 1

            # Pick a customer (first customer heavily weighted)
            cust_idx = RNG.choice(len(CUSTOMERS), p=CUSTOMER_WEIGHTS)
            cust_id, cust_name = CUSTOMERS[cust_idx]

            # Pick a region
            region = RNG.choice(REGIONS)

            # Pick a random day in the month
            day = RNG.integers(1, 29)   # max 28 avoids Feb issues
            date_str = f"2023-{month:02d}-{day:02d}"

            # Number of line items in this order (1-4)
            n_lines = RNG.choice([1, 2, 3, 4], p=[0.35, 0.35, 0.20, 0.10])

            # Pick distinct products for this order
            chosen_idxs = RNG.choice(
                len(PRODUCTS),
                size=min(n_lines, len(PRODUCTS)),
                replace=False,
                p=PRODUCT_WEIGHTS,
            )

            for prod_idx in chosen_idxs:
                name, category, unit_price, unit_cost = PRODUCTS[prod_idx]
                quantity = int(RNG.integers(1, 6))   # 1-5 units

                # Small random price variation (+/- 5%) to add realism
                price_var = float(RNG.uniform(0.95, 1.05))
                actual_price = round(unit_price * price_var, 2)
                # Cost stays fixed (supplier price)
                actual_cost = round(unit_cost, 2)

                txn_id = f"TXN-{txn_counter:06d}"
                txn_counter += 1

                rows.append({
                    "transaction_id":   txn_id,
                    "order_id":         order_id,
                    "transaction_date": date_str,
                    "customer_id":      cust_id,
                    "customer_name":    cust_name,
                    "product":          name,
                    "category":         category,
                    "region":           region,
                    "quantity":         quantity,
                    "unit_price":       actual_price,
                    "unit_cost":        actual_cost,
                })

    return pd.DataFrame(rows)


def main() -> None:
    output_path = pathlib.Path(__file__).resolve().parent / "sample_data.csv"

    print("Generating synthetic sample dataset...")
    df = generate()

    # Quick sanity checks
    assert df["transaction_id"].nunique() == len(df), "transaction_id not unique!"
    assert df["order_id"].nunique() < len(df), "No multi-product orders found!"
    assert set(df.columns) >= {
        "transaction_id", "order_id", "transaction_date",
        "customer_id", "customer_name", "product", "category",
        "region", "quantity", "unit_price", "unit_cost",
    }, "Missing required columns!"

    # Compute quick stats
    total_rows = len(df)
    total_orders = df["order_id"].nunique()
    months = df["transaction_date"].apply(lambda d: d[:7]).nunique()
    categories = df["category"].nunique()
    customers = df["customer_id"].nunique()
    products = df["product"].nunique()
    regions = df["region"].nunique()

    # Revenue check — September should have less than August
    df["month"] = df["transaction_date"].apply(lambda d: d[:7])
    monthly = df.groupby("month").apply(
        lambda g: (g["quantity"] * g["unit_price"]).sum()
    )
    aug_rev = float(monthly.get("2023-08", 0))
    sep_rev = float(monthly.get("2023-09", 0))
    decline_pct = (aug_rev - sep_rev) / aug_rev * 100 if aug_rev > 0 else 0
    df.drop(columns=["month"], inplace=True)

    # Write with synthetic-data header comment
    header = (
        "# SYNTHETIC SAMPLE DATA - Not real business data\n"
        "# Generated by data/generate_sample.py (seed=42)\n"
        "# Smart Business Data Analytics Platform\n"
        "#\n"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        df.to_csv(f, index=False)

    print(f"Saved: {output_path}")
    print(f"  Total rows (line items): {total_rows:,}")
    print(f"  Distinct orders        : {total_orders:,}  (multi-product confirmed: {total_rows > total_orders})")
    print(f"  Months covered         : {months}")
    print(f"  Categories             : {categories}")
    print(f"  Customers              : {customers}")
    print(f"  Products               : {products}")
    print(f"  Regions                : {regions}")
    print(f"  Aug 2023 revenue       : ${aug_rev:,.0f}")
    print(f"  Sep 2023 revenue       : ${sep_rev:,.0f}  (decline: {decline_pct:.1f}%)")

    # Check for negative-margin products
    df["revenue"] = df["quantity"] * df["unit_price"]
    df["cost"] = df["quantity"] * df["unit_cost"]
    df["profit"] = df["revenue"] - df["cost"]
    neg_products = (
        df.groupby("product")["profit"].sum()
        .pipe(lambda s: s[s < 0])
        .index.tolist()
    )
    print(f"  Negative-profit products: {neg_products}")


if __name__ == "__main__":
    main()
