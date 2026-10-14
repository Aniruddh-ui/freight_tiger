import math

import pandas as pd
import pytest

from cost_watch.flagging import add_anomaly_flags
from cost_watch.metrics import (
    add_history_baseline,
    add_peer_baseline,
    build_weekly_table,
    week_start,
    weekly_route_costs,
)


def shipments(rows):
    """rows: (route, route_type, date, tonnes, km, cost)"""
    df = pd.DataFrame(rows, columns=["route", "route_type", "shipment_date",
                                     "quantity_tonnes", "distance_km", "freight_cost_inr"])
    df["shipment_date"] = pd.to_datetime(df["shipment_date"])
    df["shipment_id"] = [f"S{i}" for i in range(len(df))]
    return df


def weekly_series(route, route_type, costs, start="2024-01-01"):
    weeks = pd.date_range(start, periods=len(costs), freq="7D")
    return pd.DataFrame({"route": route, "route_type": route_type,
                         "week_of": weeks, "cost_per_tonne_km": costs})


def test_week_start_is_monday_and_sunday_stays_in_same_week():
    dates = pd.Series(pd.to_datetime(["2024-01-01", "2024-01-07", "2024-01-08", "2025-12-28"]))
    assert week_start(dates).dt.strftime("%Y-%m-%d").tolist() == [
        "2024-01-01", "2024-01-01", "2024-01-08", "2025-12-22"]


def test_weekly_cost_is_total_cost_over_total_tonne_km():
    df = shipments([
        ("A-B", "Short", "2024-01-01", 10, 100, 2000),  # 2.0 per tonne-km
        ("A-B", "Short", "2024-01-03", 30, 100, 12000),  # 4.0 per tonne-km
    ])
    weekly = weekly_route_costs(df)
    # (2000 + 12000) / (1000 + 3000) = 3.5, not the 3.0 a mean of ratios would give
    assert weekly["cost_per_tonne_km"].tolist() == [3.5]


def test_history_uses_only_prior_weeks_and_at_most_eight():
    costs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0]
    out = add_history_baseline(weekly_series("A-B", "Short", costs))
    assert math.isnan(out["history_avg"].iloc[0])
    assert out["history_weeks"].iloc[0] == 0
    assert out["history_avg"].iloc[1] == 1.0          # only week 1 available
    assert out["history_avg"].iloc[3] == 2.0          # mean of 1,2,3 (partial window)
    assert out["history_avg"].iloc[9] == pytest.approx(sum(range(2, 10)) / 8)  # weeks 2..9
    assert out["history_weeks"].iloc[9] == 8


def test_history_window_is_calendar_based_when_a_week_is_missing():
    df = weekly_series("A-B", "Short", [1.0] * 9 + [5.0])
    df = df.drop(index=4)  # route had no shipments that week
    out = add_history_baseline(df)
    assert out["history_weeks"].iloc[-1] == 7  # 8 calendar weeks, one of them empty


def test_history_is_computed_per_route():
    df = pd.concat([weekly_series("A-B", "Short", [1.0, 1.0]),
                    weekly_series("C-D", "Short", [9.0, 9.0])])
    out = add_history_baseline(df)
    assert out.set_index("route").loc["C-D", "history_avg"].tolist()[1] == 9.0


def test_peer_average_excludes_the_route_itself_and_other_types():
    df = pd.concat([
        weekly_series("A", "Medium", [2.0]),
        weekly_series("B", "Medium", [4.0]),
        weekly_series("C", "Medium", [6.0]),
        weekly_series("D", "Long", [100.0]),
    ])
    out = add_peer_baseline(df).set_index("route")
    assert out.loc["A", "peer_avg"] == 5.0
    assert out.loc["B", "peer_avg"] == 4.0
    assert math.isnan(out.loc["D", "peer_avg"])  # no other Long route


def test_flags_need_a_rise_past_the_threshold_and_ignore_missing_baselines():
    df = pd.DataFrame({"vs_history_pct": [float("nan"), 14.9, 15.0, -30.0],
                       "vs_peers_pct": [19.9, float("nan"), 0.0, 20.0]})
    out = add_anomaly_flags(df, own_threshold=15, peer_threshold=20)
    assert out["is_anomaly"].tolist() == [False, False, True, True]


def test_real_data_matches_the_sample_rows():
    from cost_watch.config import SHIPMENTS_CSV
    from cost_watch.load import load_shipments

    weekly = build_weekly_table(load_shipments(SHIPMENTS_CSV))
    row = weekly[(weekly.route == "Delhi-Jaipur") & (weekly.week_of == "2024-11-11")].iloc[0]
    assert round(row.cost_per_tonne_km, 2) == 4.17
    assert round(row.vs_history_pct, 1) == 35.5
    assert round(row.vs_peers_pct, 1) == 21.0
