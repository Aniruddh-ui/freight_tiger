"""Decide which route-weeks look like an unusual cost rise."""
import pandas as pd

from .config import OWN_HISTORY_THRESHOLD_PCT, PEER_THRESHOLD_PCT


def add_anomaly_flags(
    weekly: pd.DataFrame,
    own_threshold: float = OWN_HISTORY_THRESHOLD_PCT,
    peer_threshold: float = PEER_THRESHOLD_PCT,
) -> pd.DataFrame:
    """Mark weeks whose cost is up by at least the threshold vs either baseline.

    A missing baseline (first week of a route, or no peers that week) can never
    trigger a flag: NaN >= x is False.
    """
    out = weekly.copy()
    out["rise_vs_history"] = out["vs_history_pct"] >= own_threshold
    out["rise_vs_peers"] = out["vs_peers_pct"] >= peer_threshold
    out["is_anomaly"] = out["rise_vs_history"] | out["rise_vs_peers"]
    return out
