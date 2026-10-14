"""Weekly cost per tonne-km and the two comparison baselines from the brief."""
import pandas as pd

from .config import HISTORY_WINDOW_WEEKS


def week_start(dates: pd.Series) -> pd.Series:
    """Monday of the Monday-Sunday week each date falls in."""
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize()


def weekly_route_costs(shipments: pd.DataFrame) -> pd.DataFrame:
    """One row per (route, week) with cost per tonne-km for that week.

    Weekly cost per tonne-km = total freight cost / total tonne-km, i.e. the
    brief's formula applied to the week's totals. (Averaging per-shipment
    ratios instead gives slightly different numbers that do not match the
    sample output, e.g. 4.16 vs 4.17 for Delhi-Jaipur 2024-11-11.)
    """
    df = shipments.assign(
        week_of=week_start(shipments["shipment_date"]),
        tonne_km=shipments["quantity_tonnes"] * shipments["distance_km"],
    )
    weekly = df.groupby(["route", "route_type", "week_of"], as_index=False).agg(
        total_cost=("freight_cost_inr", "sum"),
        total_tonne_km=("tonne_km", "sum"),
        shipments=("shipment_id", "count"),
    )
    weekly["cost_per_tonne_km"] = weekly["total_cost"] / weekly["total_tonne_km"]
    return weekly.sort_values(["route", "week_of"]).reset_index(drop=True)


def add_history_baseline(weekly: pd.DataFrame, window_weeks: int = HISTORY_WINDOW_WEEKS) -> pd.DataFrame:
    """Add the route's trailing average over the previous `window_weeks` weeks.

    The window is calendar based: [week - 8 weeks, week), so the current week
    is never included (no look-ahead). If fewer prior weeks exist we average
    what is there; `history_weeks` records how many weeks were used.
    """
    out = weekly.sort_values(["route", "week_of"]).reset_index(drop=True)
    window = f"{7 * window_weeks}D"
    for _, idx in out.groupby("route").groups.items():
        series = out.loc[idx].set_index("week_of")["cost_per_tonne_km"]
        rolling = series.rolling(window, closed="left")
        out.loc[idx, "history_avg"] = rolling.mean().to_numpy()
        out.loc[idx, "history_weeks"] = rolling.count().fillna(0).to_numpy()
    out["history_weeks"] = out["history_weeks"].astype(int)
    return out


def add_peer_baseline(weekly: pd.DataFrame) -> pd.DataFrame:
    """Add the same-week average across *other* routes of the same route_type.

    Peer average = (sum of all routes in the group - this route) / (n - 1).
    It is a plain average of route-level weekly values, so each route counts
    once regardless of how many shipments it had.
    """
    out = weekly.copy()
    group = out.groupby(["route_type", "week_of"])["cost_per_tonne_km"]
    total = group.transform("sum")
    peers = group.transform("count") - 1
    out["peer_routes"] = peers
    out["peer_avg"] = ((total - out["cost_per_tonne_km"]) / peers).where(peers > 0)
    return out


def pct_change(value: pd.Series, baseline: pd.Series) -> pd.Series:
    return (value / baseline - 1) * 100


def build_weekly_table(shipments: pd.DataFrame) -> pd.DataFrame:
    """Weekly costs plus both baselines and the % differences against them."""
    weekly = weekly_route_costs(shipments)
    weekly = add_history_baseline(weekly)
    weekly = add_peer_baseline(weekly)
    weekly["vs_history_pct"] = pct_change(weekly["cost_per_tonne_km"], weekly["history_avg"])
    weekly["vs_peers_pct"] = pct_change(weekly["cost_per_tonne_km"], weekly["peer_avg"])
    return weekly.sort_values(["route", "week_of"]).reset_index(drop=True)
