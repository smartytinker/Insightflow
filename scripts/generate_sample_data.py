"""Generate reproducible sample datasets for InsightFlow.

Usage:
    python scripts/generate_sample_data.py

The script is deterministic (seed 42) and intentionally includes missing
values, duplicates and unusual observations so cleaning and anomaly detection
have realistic material to work with.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "sample_data"

CATEGORY_CATALOG = {
    "Electronics": {
        "products": ["Wireless Headphones", "4K Monitor", "Mechanical Keyboard", "USB-C Dock"],
        "price_range": (45, 650),
        "weight": 0.32,
    },
    "Home & Kitchen": {
        "products": ["Espresso Machine", "Air Fryer", "Blender", "Cookware Set"],
        "price_range": (25, 420),
        "weight": 0.24,
    },
    "Sports": {
        "products": ["Running Shoes", "Yoga Mat", "Cycling Helmet", "Dumbbell Set"],
        "price_range": (18, 260),
        "weight": 0.18,
    },
    "Beauty": {
        "products": ["Skincare Set", "Hair Dryer", "Perfume", "Makeup Kit"],
        "price_range": (12, 180),
        "weight": 0.16,
    },
    "Office": {
        "products": ["Ergonomic Chair", "Standing Desk", "Desk Lamp", "Notebook Pack"],
        "price_range": (8, 520),
        "weight": 0.10,
    },
}
REGIONS = ["North", "South", "East", "West", "Central"]


def _pick_category(rng: np.random.Generator, size: int) -> np.ndarray:
    categories = list(CATEGORY_CATALOG)
    weights = np.array([CATEGORY_CATALOG[c]["weight"] for c in categories])
    weights = weights / weights.sum()
    return rng.choice(categories, size=size, p=weights)


def generate_sales(rng: np.random.Generator, rows: int = 750) -> pd.DataFrame:
    """Create a sales transactions dataset with realistic distributions."""
    categories = _pick_category(rng, rows)
    products = []
    unit_prices = []
    for category in categories:
        catalog = CATEGORY_CATALOG[category]
        product = rng.choice(catalog["products"])
        low, high = catalog["price_range"]
        # Log-normal-like pricing within each product's range.
        price = float(np.round(rng.uniform(low, high), 2))
        products.append(product)
        unit_prices.append(price)

    start = pd.Timestamp("2024-01-01")
    offsets = rng.integers(0, 545, size=rows)
    dates = start + pd.to_timedelta(offsets, unit="D")

    # Seasonality: more volume in Nov/Dec, fewer in Jan/Feb.
    quantities = rng.integers(1, 9, size=rows)
    month_factor = np.where(dates.month.isin([11, 12]), 1.35, 1.0)
    month_factor = np.where(dates.month.isin([1, 2]), 0.8, month_factor)
    quantities = np.maximum(1, np.round(quantities * month_factor).astype(int))

    regions = rng.choice(REGIONS, size=rows, p=[0.24, 0.21, 0.2, 0.22, 0.13])
    revenue = np.round(np.array(unit_prices) * quantities, 2)

    frame = pd.DataFrame(
        {
            "transaction_id": [f"TXN-{100000 + i}" for i in range(rows)],
            "transaction_date": dates.strftime("%Y-%m-%d"),
            "product": products,
            "category": categories,
            "region": regions,
            "quantity": quantities,
            "unit_price": np.round(unit_prices, 2),
            "revenue": revenue,
            "customer_id": [f"CUST-{rng.integers(1000, 1650)}" for _ in range(rows)],
        }
    )

    # Missing values in a realistic pattern.
    missing_region = rng.choice(rows, size=int(rows * 0.03), replace=False)
    missing_customer = rng.choice(rows, size=int(rows * 0.05), replace=False)
    missing_price = rng.choice(rows, size=int(rows * 0.02), replace=False)
    frame.loc[missing_region, "region"] = np.nan
    frame.loc[missing_customer, "customer_id"] = np.nan
    frame.loc[missing_price, "unit_price"] = np.nan

    # A few unusual bulk orders and data-entry spikes.
    outlier_rows = rng.choice(rows, size=6, replace=False)
    frame.loc[outlier_rows[:3], "quantity"] = [180, 240, 320]
    frame.loc[outlier_rows[:3], "revenue"] = (
        frame.loc[outlier_rows[:3], "quantity"] * frame.loc[outlier_rows[:3], "unit_price"]
    ).round(2)
    frame.loc[outlier_rows[3:5], "unit_price"] = [4999.99, 3899.5]
    frame.loc[outlier_rows[3:5], "revenue"] = (
        frame.loc[outlier_rows[3:5], "quantity"] * frame.loc[outlier_rows[3:5], "unit_price"]
    ).round(2)

    # Duplicate a handful of records exactly (including IDs) to exercise cleaning.
    duplicate_rows = frame.iloc[rng.choice(rows, size=9, replace=False)].copy()
    frame = pd.concat([frame, duplicate_rows], ignore_index=True)

    return frame.sample(frac=1.0, random_state=SEED).reset_index(drop=True)


def generate_marketing(rng: np.random.Generator, rows: int = 420) -> pd.DataFrame:
    """Create a marketing campaign performance dataset."""
    channels = ["Search", "Social", "Email", "Display", "Referral"]
    channel_weights = np.array([0.24, 0.26, 0.2, 0.2, 0.1])
    channel_cpm = {"Search": 18, "Social": 9, "Email": 2, "Display": 6, "Referral": 4}
    channel_ctr = {
        "Search": 0.045,
        "Social": 0.018,
        "Email": 0.028,
        "Display": 0.009,
        "Referral": 0.05,
    }
    channel_cvr = {
        "Search": 0.06,
        "Social": 0.012,
        "Email": 0.035,
        "Display": 0.008,
        "Referral": 0.07,
    }
    campaign_names = {
        "Search": ["Brand Search", "Competitor Conquest", "Product Search"],
        "Social": ["Spring Social", "Creator Collab", "Retargeting Social"],
        "Email": ["Weekly Digest", "Win-back Email", "VIP Newsletter"],
        "Display": ["Programmatic Display", "Lookalike Display", "Awareness Banner"],
        "Referral": ["Partner Referral", "Advocate Program", "Affiliate Boost"],
    }

    selected_channels = rng.choice(channels, size=rows, p=channel_weights)
    impressions = []
    clicks = []
    conversions = []
    spend = []
    revenue = []
    names = []
    dates = []

    start = pd.Timestamp("2024-01-01")
    for channel in selected_channels:
        base_impressions = {
            "Search": rng.integers(8_000, 55_000),
            "Social": rng.integers(25_000, 160_000),
            "Email": rng.integers(5_000, 42_000),
            "Display": rng.integers(40_000, 220_000),
            "Referral": rng.integers(2_000, 18_000),
        }[channel]
        noise = rng.uniform(0.7, 1.3)
        impression_count = int(base_impressions * noise)
        click_count = int(impression_count * channel_ctr[channel] * rng.uniform(0.6, 1.5))
        conversion_count = int(click_count * channel_cvr[channel] * rng.uniform(0.5, 1.7))
        cost = (impression_count / 1000) * channel_cpm[channel] * rng.uniform(0.8, 1.2)
        revenue_value = conversion_count * rng.uniform(45, 260)

        impressions.append(impression_count)
        clicks.append(max(click_count, 0))
        conversions.append(max(conversion_count, 0))
        spend.append(round(cost, 2))
        revenue.append(round(revenue_value, 2))
        names.append(str(rng.choice(campaign_names[channel])))
        dates.append(start + pd.to_timedelta(int(rng.integers(0, 365)), unit="D"))

    frame = pd.DataFrame(
        {
            "campaign_id": [f"CMP-{2000 + i}" for i in range(rows)],
            "campaign_name": names,
            "channel": selected_channels,
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "spend": spend,
            "revenue": revenue,
            "campaign_date": [date.strftime("%Y-%m-%d") for date in dates],
        }
    )

    missing_spend = rng.choice(rows, size=int(rows * 0.04), replace=False)
    missing_clicks = rng.choice(rows, size=int(rows * 0.03), replace=False)
    frame.loc[missing_spend, "spend"] = np.nan
    frame.loc[missing_clicks, "clicks"] = np.nan

    # A few underperforming / overspending campaigns.
    outlier_rows = rng.choice(rows, size=5, replace=False)
    frame.loc[outlier_rows[:2], "spend"] = frame.loc[outlier_rows[:2], "spend"] * 9
    frame.loc[outlier_rows[2:4], "conversions"] = 0
    frame.loc[outlier_rows[4], "impressions"] = int(frame["impressions"].max() * 2.5)

    return frame.sample(frac=1.0, random_state=SEED + 1).reset_index(drop=True)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    sales = generate_sales(rng)
    marketing = generate_marketing(rng)

    sales_path = OUTPUT_DIR / "sales.csv"
    marketing_path = OUTPUT_DIR / "marketing_campaigns.csv"
    sales.to_csv(sales_path, index=False)
    marketing.to_csv(marketing_path, index=False)

    print(f"Wrote {sales_path} ({len(sales)} rows, {len(sales.columns)} columns)")
    print(f"Wrote {marketing_path} ({len(marketing)} rows, {len(marketing.columns)} columns)")


if __name__ == "__main__":
    main()
