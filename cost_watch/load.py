"""Load and validate the raw shipment file."""
import pandas as pd

REQUIRED_COLUMNS = [
    "shipment_id",
    "origin",
    "destination",
    "route_type",
    "quantity_tonnes",
    "distance_km",
    "freight_cost_inr",
    "shipment_date",
]


def load_shipments(path) -> pd.DataFrame:
    """Read shipments, check the data is usable, and add a `route` column.

    We fail loudly on bad data instead of silently dropping rows, because a
    dropped row would quietly change every weekly number downstream.
    """
    df = pd.read_csv(path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"shipment file is missing columns: {missing}")
    if df[REQUIRED_COLUMNS].isna().any().any():
        raise ValueError("shipment file has blank values in required columns")
    if df["shipment_id"].duplicated().any():
        raise ValueError("shipment file has duplicate shipment_id values")
    if (df["quantity_tonnes"] <= 0).any() or (df["distance_km"] <= 0).any():
        raise ValueError("quantity_tonnes and distance_km must be positive")
    if (df["freight_cost_inr"] < 0).any():
        raise ValueError("freight_cost_inr cannot be negative")

    df["shipment_date"] = pd.to_datetime(df["shipment_date"], format="%Y-%m-%d")
    df["route"] = df["origin"].str.strip() + "-" + df["destination"].str.strip()
    df["route_type"] = df["route_type"].str.strip()

    types_per_route = df.groupby("route")["route_type"].nunique()
    if (types_per_route > 1).any():
        bad = types_per_route[types_per_route > 1].index.tolist()
        raise ValueError(f"routes with more than one route_type: {bad}")

    return df
