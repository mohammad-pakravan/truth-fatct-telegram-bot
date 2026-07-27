from __future__ import annotations

import math
from typing import Optional


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle distance between two WGS84 points in kilometers."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def within_radius(
    lat1: Optional[float],
    lon1: Optional[float],
    lat2: Optional[float],
    lon2: Optional[float],
    radius_km: Optional[int],
) -> bool:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return False
    if radius_km is None or radius_km <= 0:
        return False
    return haversine_km(lat1, lon1, lat2, lon2) <= float(radius_km)
