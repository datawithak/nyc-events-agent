"""Borough detection from ZIP, city name, or lat/lon (rough polygons)."""
from __future__ import annotations

from typing import Optional

BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")

# ZIP prefixes are 3 digits in NYC; this is the ranges per borough.
# Source: USPS + NYC.gov reference.
ZIP_RANGES = [
    ("Manhattan", range(10001, 10283)),       # 100xx-102xx
    ("Bronx",     range(10451, 10476)),
    ("Staten Island", range(10301, 10315)),
    ("Queens",    range(11001, 11110)),       # 110xx, plus 111-114, 116
    ("Queens",    range(11351, 11698)),
    ("Brooklyn",  range(11201, 11257)),
]

CITY_ALIASES = {
    "new york": "Manhattan",
    "new york city": "Manhattan",
    "nyc": "Manhattan",
    "manhattan": "Manhattan",
    "brooklyn": "Brooklyn",
    "queens": "Queens",
    "long island city": "Queens",
    "astoria": "Queens",
    "flushing": "Queens",
    "jamaica": "Queens",
    "the bronx": "Bronx",
    "bronx": "Bronx",
    "staten island": "Staten Island",
}


def borough_from_zip(zip_code: str | int | None) -> Optional[str]:
    if zip_code is None:
        return None
    try:
        z = int(str(zip_code)[:5])
    except (TypeError, ValueError):
        return None
    for name, rng in ZIP_RANGES:
        if z in rng:
            return name
    return None


def borough_from_city(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    return CITY_ALIASES.get(city.strip().lower())


def borough_from_address(address: Optional[str]) -> Optional[str]:
    """Cheap heuristic: scan address text for borough names or NYC ZIPs."""
    if not address:
        return None
    a = address.lower()
    for name in BOROUGHS:
        if name.lower() in a:
            return name
    # Pull a 5-digit ZIP if present.
    import re
    m = re.search(r"\b(\d{5})\b", a)
    if m:
        return borough_from_zip(m.group(1))
    return None


def borough_from_latlon(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    """Very rough box check — falls back when no address is present.
    Boundaries are approximate; refine with shapefiles if you need precision."""
    if lat is None or lon is None:
        return None
    # Staten Island: south + west.
    if lat < 40.65 and lon < -74.05:
        return "Staten Island"
    # Bronx: north of ~40.80.
    if lat > 40.80 and lon > -73.93:
        return "Bronx"
    # Queens: east of ~-73.92.
    if lon > -73.92 and lat > 40.55 and lat < 40.80:
        return "Queens"
    # Brooklyn: south of ~40.74, west-ish.
    if lat < 40.74 and lon > -74.05:
        return "Brooklyn"
    # Manhattan: the rest of the central rectangle.
    if -74.02 < lon < -73.91 and 40.70 < lat < 40.88:
        return "Manhattan"
    return None


def detect_borough(
    *,
    address: Optional[str] = None,
    city: Optional[str] = None,
    zip_code: Optional[str | int] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Optional[str]:
    return (
        borough_from_zip(zip_code)
        or borough_from_city(city)
        or borough_from_address(address)
        or borough_from_latlon(lat, lon)
    )
