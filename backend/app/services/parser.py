import pandas as pd
from typing import BinaryIO

REQUIRED = {"date", "hour", "footfall", "transactions", "sales"}
REQUIRED_LINES = {"date", "hour", "transaction_id", "sku", "qty", "unit_price"}
REQUIRED_PRODUCTS = {"sku", "name", "cost_price", "sell_price"}

def parse_excel(file: BinaryIO, default_store: str = "S1") -> pd.DataFrame:
    df = pd.read_excel(file)
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["hour"] = df["hour"].astype(int)
    df["footfall"] = df["footfall"].astype(int)
    df["transactions"] = df["transactions"].astype(int)
    df["sales"] = df["sales"].astype(float)

    if "store_id" not in df.columns:
        df["store_id"] = default_store
    else:
        df["store_id"] = df["store_id"].astype(str)

    # Drop invalid rows rather than failing the whole upload
    df = df[(df["hour"] >= 0) & (df["hour"] <= 23)]
    df = df[df["footfall"] >= 0]
    df = df[df["transactions"] >= 0]

    return df.reset_index(drop=True)

def parse_sales_lines(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = REQUIRED_LINES - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["hour"] = df["hour"].astype(int)
    df["transaction_id"] = df["transaction_id"].astype(str)
    df["sku"] = df["sku"].astype(str)
    df["qty"] = df["qty"].astype(int)
    df["unit_price"] = df["unit_price"].astype(float)
    return df.reset_index(drop=True)


def parse_product_catalog(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = REQUIRED_PRODUCTS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df["sku"] = df["sku"].astype(str)
    df["name"] = df["name"].astype(str)
    df["cost_price"] = df["cost_price"].astype(float)
    df["sell_price"] = df["sell_price"].astype(float)
    return df.reset_index(drop=True)