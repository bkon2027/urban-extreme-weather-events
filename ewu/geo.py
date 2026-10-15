"""Pure geographic rules: distances, urban-area edges, the size-scaled rural buffer, coast and airport flags.

No file or network access: geometries and lookup functions are passed in as values.
Distances are in km. Geometries are shapely polygons in lon/lat degrees (Census TIGER, NAD83).
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable

import numpy as np
import shapely
from shapely.geometry import Point

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQUATOR = 111.320

AIRPORT_NAME = re.compile(r"(\bAP\b|AIRPORT|\bINTL\b|\bRGNL\b|\bFLD\b|\bMUNI\b|\bARPT\b|\bAIR PK\b|\bAFB\b|\bNAS\b|\bAAF\b)")
# Airports whose GHCN names lack an airport word, confirmed by coordinates (Cleveland Hopkins, Lubbock, Dodge City).
CONFIRMED_AIRPORTS = frozenset({"USW00014820", "USW00023042", "USW00013985"})
# Named after an airport that no longer exists: Denver-Stapleton closed in 1995 (now a neighborhood).
NOT_AIRPORTS = frozenset({"USW00023062"})


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _to_local_km(lat0: float, lon0: float):
    """Equirectangular projection centred on (lat0, lon0); accurate to <1% within ~200 km."""
    kx = KM_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat0))  # km per degree of longitude at lat0
    def f(coords: np.ndarray) -> np.ndarray:
        return np.column_stack(((coords[:, 0] - lon0) * kx, (coords[:, 1] - lat0) * KM_PER_DEG_LAT))
    return f


def distance_to_edge_km(lat: float, lon: float, polygon) -> float:
    """Distance from a point to a polygon's boundary in km; 0.0 if the point is inside the polygon."""
    if polygon.contains(Point(lon, lat)):
        return 0.0
    local = shapely.transform(polygon, _to_local_km(lat, lon))
    return float(local.exterior.distance(Point(0, 0)) if local.geom_type == "Polygon"
                 else min(g.exterior.distance(Point(0, 0)) for g in local.geoms))


def effective_radius_km(land_area_m2: float) -> float:
    """Radius of a circle with the urban area's land area: a size measure for the buffer rule."""
    if land_area_m2 <= 0:
        raise ValueError("land area must be positive")
    return math.sqrt(land_area_m2 / math.pi) / 1000.0


def required_buffer_km(radius_km: float, min_km: float = 10.0, radius_fraction: float = 0.5) -> float:
    """Minimum distance a rural station must sit outside the urban edge: larger for larger cities."""
    return max(min_km, radius_fraction * radius_km)


def passes_buffer(rural_edge_km: float, radius_km: float, min_km: float = 10.0, radius_fraction: float = 0.5) -> bool:
    return rural_edge_km >= required_buffer_km(radius_km, min_km, radius_fraction)


def coast_distance_km(lat: float, lon: float, is_land: Callable, max_km: float = 100.0, step_km: float = 2.0) -> float:
    """Distance to the nearest ocean grid point (km), searched on a grid up to max_km; returns max_km if none.

    is_land(lat_array, lon_array) -> bool array (e.g. global_land_mask.globe.is_land). Lakes count as land.
    """
    n = int(max_km // step_km)
    offsets = np.arange(-n, n + 1) * step_km
    dx, dy = np.meshgrid(offsets, offsets)
    dist = np.hypot(dx, dy)
    keep = dist <= max_km
    dx, dy, dist = dx[keep], dy[keep], dist[keep]
    lats = lat + dy / KM_PER_DEG_LAT
    lons = lon + dx / (KM_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat)))
    ocean = ~np.asarray(is_land(lats, lons), dtype=bool)
    return float(dist[ocean].min()) if ocean.any() else float(max_km)


def coastal_mismatch(urban_coast_km: float, rural_coast_km: float, near_km: float = 25.0) -> bool:
    """True when exactly one station of the pair is near the ocean: the sea, not the city, may drive the gap."""
    return (urban_coast_km < near_km) != (rural_coast_km < near_km)


def is_airport(station_id: str, name: str) -> bool:
    if station_id in NOT_AIRPORTS:
        return False
    return station_id in CONFIRMED_AIRPORTS or bool(AIRPORT_NAME.search(name.upper()))


def is_interior_west(urban_lon: float, urban_coast_km: float, rural_coast_km: float,
                     lon_max: float = -104.0, inland_km: float = 100.0) -> bool:
    """Pair in the mountain/basin interior West: west of lon_max with no ocean within inland_km of either station.

    A sensitivity flag for terrain: valley and basin sites there are prone to night-time cold-air pooling.
    """
    return urban_lon < lon_max and urban_coast_km >= inland_km and rural_coast_km >= inland_km
