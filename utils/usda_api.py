"""
USDA MARS API client — Chicago Terminal Market Fruit Prices (HX_FV010, report ID 2290)
Docs: https://mymarketnews.ams.usda.gov/mars-api/getting-started/basic-instructions
Auth: HTTP Basic auth, API key as username, empty password.
"""

import requests
import streamlit as st
from datetime import datetime

CHICAGO_REPORT_ID = 2290   # HX_FV010 — Chicago Terminal Market Fruit Prices
MIAMI_REPORT_ID   = 2310   # MH_FV010 — Miami Terminal Market (backup for tropicals)
BASE_URL = "https://marsapi.ams.usda.gov/services/v1.2/reports"

# Map our fruit names → terms to search in USDA commodity_name field
FRUIT_USDA_MAP = {
    "Jackfruit":             ["Jackfruit"],
    "Soursop (Guanábana)":  ["Soursop", "Guanabana", "Guanábana"],
    "Dragonfruit (Pitaya)":  ["Dragon Fruit", "Pitaya"],
    "Starfruit (Carambola)": ["Carambola", "Star Fruit"],
    "Tomatillos":            ["Tomatillo"],          # in vegetable reports; rarely in fruit
    "Prickly Pear":          ["Cactus Pear", "Prickly Pear"],
    "Lychee":                ["Lychee", "Litchi"],
    "Sitafal (Sugar Apple)": ["Sugar Apple", "Custard Apple", "Atemoya", "Cherimoya"],
}

# Fallback hypothetical wholesale costs ($/lb) used when USDA has no data
FALLBACK_COSTS = {
    "Jackfruit":             {"low": 0.80, "high": 1.40, "unit": "lb", "note": "Hypothetical"},
    "Soursop (Guanábana)":  {"low": 3.50, "high": 6.00, "unit": "lb", "note": "Hypothetical"},
    "Dragonfruit (Pitaya)":  {"low": 3.00, "high": 5.00, "unit": "ea", "note": "Hypothetical"},
    "Starfruit (Carambola)": {"low": 1.00, "high": 2.50, "unit": "lb", "note": "Hypothetical"},
    "Tomatillos":            {"low": 0.60, "high": 1.20, "unit": "lb", "note": "Hypothetical"},
    "Prickly Pear":          {"low": 0.50, "high": 1.50, "unit": "ea", "note": "Hypothetical"},
    "Lychee":                {"low": 4.00, "high": 8.00, "unit": "lb", "note": "Hypothetical"},
    "Sitafal (Sugar Apple)": {"low": 3.00, "high": 6.00, "unit": "ea", "note": "Hypothetical"},
}

# Typical shrink rates for specialty/tropical produce
# Shrink rates updated from USDA ERS EIB-155 (supermarket shrink study, range 4.1%–43.1%),
# lychee postharvest loss literature (20–50%), and custard apple / soursop perishability research.
SHRINK_RATES = {
    "Jackfruit":             0.12,  # Whole fruit durable but ripens rapidly once it starts
    "Soursop (Guanábana)":  0.25,  # Extremely fragile skin, bruises in transit, short window
    "Dragonfruit (Pitaya)":  0.10,  # Tough skin helps; still needs specialty handling
    "Starfruit (Carambola)": 0.15,  # Ridge tips bruise easily, moisture loss visible quickly
    "Tomatillos":            0.06,  # Husk provides good protection
    "Prickly Pear":          0.10,  # Outer skin is protective
    "Lychee":                0.20,  # Postharvest loss 20–50%; shell browning drives markdowns
    "Sitafal (Sugar Apple)": 0.30,  # 4-day room-temp shelf life, rapid softening — papaya-class
}

# Seasonality notes
SEASONALITY = {
    "Jackfruit":             "Year-round (peak Mar–Sep); import from Mexico/Southeast Asia.",
    "Soursop (Guanábana)":  "Year-round from Caribbean/Central America; prices spike Nov–Jan.",
    "Dragonfruit (Pitaya)":  "Peak Jul–Nov (domestic CA/FL); year-round via imports.",
    "Starfruit (Carambola)": "Peak Aug–Feb from Florida; some CA and imports year-round.",
    "Tomatillos":            "Year-round from Mexico; peak summer quality.",
    "Prickly Pear":          "Peak Sep–Dec; also spring. Primarily from Mexico.",
    "Lychee":                "Highly seasonal: May–Jul from Florida/CA. Import Nov–Jan.",
    "Sitafal (Sugar Apple)": "Limited US supply; primarily imported. Sep–Jan peak.",
}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_report(api_key: str, report_id: int, last_n: int = 1) -> list[dict]:
    """Fetch the latest N reports from MARS API. Returns list of row dicts."""
    url = f"{BASE_URL}/{report_id}/report details?lastReports={last_n}"
    try:
        resp = requests.get(url, auth=(api_key, ""), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 401:
            raise ValueError("Invalid API key — check your USDA My Market News key.")
        raise RuntimeError(f"USDA API error {resp.status_code}: {e}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error reaching USDA API: {e}")


def _get_field(row: dict, *candidates, default=None):
    """Try multiple field name variants; return first match."""
    for k in candidates:
        if k in row and row[k] is not None and row[k] != "":
            return row[k]
    return default


def parse_prices(rows: list[dict]) -> dict[str, dict]:
    """
    Parse raw MARS API rows into a dict keyed by our fruit names.
    Each entry: {low, high, unit, package, origin, date, source}
    """
    results = {}
    for fruit, terms in FRUIT_USDA_MAP.items():
        matches = []
        for row in rows:
            commodity = str(_get_field(row, "commodity_name", "Commodity", "commodity", default=""))
            if any(t.lower() in commodity.lower() for t in terms):
                low  = _get_field(row, "low_price",    "Low Price",   "low",  default=None)
                high = _get_field(row, "high_price",   "High Price",  "high", default=None)
                pkg  = _get_field(row, "package",      "Package",     "unit_of_sale", default="")
                orig = _get_field(row, "origin",       "Origin",      "origin_district", default="")
                date = _get_field(row, "report_date",  "Report Date", "published_date", default="")
                env  = _get_field(row, "environment",  "Environment", default="Conventional")
                if low is not None:
                    try:
                        matches.append({
                            "low":     float(low),
                            "high":    float(high) if high else float(low),
                            "package": pkg,
                            "origin":  orig,
                            "date":    date,
                            "env":     env,
                        })
                    except (ValueError, TypeError):
                        pass
        if matches:
            # Take the conventional match if available, else first
            conv = [m for m in matches if "organic" not in m["env"].lower()]
            best = conv[0] if conv else matches[0]
            results[fruit] = {
                "low":     best["low"],
                "high":    best["high"],
                "package": best["package"],
                "origin":  best["origin"],
                "date":    best["date"],
                "source":  "USDA Chicago Terminal Market",
            }
    return results


def get_wholesale_prices(api_key: str) -> tuple[dict[str, dict], str | None]:
    """
    Fetch and parse wholesale prices. Returns (prices_dict, error_string_or_None).
    prices_dict maps fruit name → {low, high, unit, package, origin, date, source}.
    Fruits not found in USDA data fall back to FALLBACK_COSTS.
    """
    try:
        rows = fetch_report(api_key, CHICAGO_REPORT_ID, last_n=1)
        usda_prices = parse_prices(rows)

        # Merge: USDA where available, fallback otherwise
        all_prices = {}
        for fruit, fb in FALLBACK_COSTS.items():
            if fruit in usda_prices:
                all_prices[fruit] = usda_prices[fruit]
            else:
                # Also try Miami for tropicals not in Chicago
                all_prices[fruit] = {**fb, "source": "Hypothetical estimate",
                                     "date": "", "package": "", "origin": ""}
        return all_prices, None

    except ValueError as e:
        return {f: {**fb, "source": "Hypothetical estimate", "date": "", "package": "", "origin": ""}
                for f, fb in FALLBACK_COSTS.items()}, str(e)
    except RuntimeError as e:
        return {f: {**fb, "source": "Hypothetical estimate", "date": "", "package": "", "origin": ""}
                for f, fb in FALLBACK_COSTS.items()}, str(e)


# Freight cost estimates ($/lb) for refrigerated transport to Chicago distribution center.
# Lanes: Miami → Chicago (~1,300 mi) and LA/Long Beach → Chicago (~2,000 mi).
# Source: USDA AMS Transportation & Marketing Program lane studies; DAT Freight rate benchmarks.
# Low = off-peak / high-season domestic supply; High = peak import season / tight capacity.
FREIGHT_COSTS = {
    "Jackfruit": {
        "low": 0.18, "high": 0.28,
        "origin": "Thailand / Vietnam / Mexico",
        "port": "LA/Long Beach or Laredo TX",
        "note": "Primarily air or reefer container from SE Asia; Mexico trucked directly.",
    },
    "Soursop (Guanábana)": {
        "low": 0.14, "high": 0.22,
        "origin": "Caribbean / Central America",
        "port": "Miami",
        "note": "Miami → Chicago reefer truck (~1,300 mi). Peak Nov–Jan tightens capacity.",
    },
    "Dragonfruit (Pitaya)": {
        "low": 0.12, "high": 0.20,
        "origin": "Vietnam / Mexico / Central America",
        "port": "LA/Long Beach or Laredo TX",
        "note": "Domestic CA/FL supply in peak season reduces freight significantly.",
    },
    "Starfruit (Carambola)": {
        "low": 0.08, "high": 0.14,
        "origin": "Florida (domestic) / Malaysia",
        "port": "Miami (imports) or direct truck from FL",
        "note": "Florida domestic supply = short haul; imports via Miami when out of season.",
    },
    "Tomatillos": {
        "low": 0.05, "high": 0.09,
        "origin": "Mexico",
        "port": "Laredo TX / McAllen TX",
        "note": "High-volume, well-established Mexico–Chicago truck lane. Lowest freight of group.",
    },
    "Prickly Pear": {
        "low": 0.06, "high": 0.10,
        "origin": "Mexico",
        "port": "Laredo TX / El Paso TX",
        "note": "Similar lane to tomatillos; slightly higher due to lower volume.",
    },
    "Lychee": {
        "low": 0.15, "high": 0.25,
        "origin": "Florida / California (domestic); China / SE Asia (imports)",
        "port": "Direct truck (domestic) or LA/Long Beach (imports)",
        "note": "Highly seasonal — domestic May–Jul is cheapest. Import Nov–Jan via air is expensive.",
    },
    "Sitafal (Sugar Apple)": {
        "low": 0.18, "high": 0.30,
        "origin": "Caribbean / SE Asia",
        "port": "Miami or LA/Long Beach",
        "note": "Limited US supply; often air-freighted due to perishability, raising cost significantly.",
    },
}


def financial_metrics(fruit: str, wholesale_low: float, wholesale_high: float,
                       markup_pct: float, shrink_override: float | None = None,
                       freight_multiplier: float = 1.0,
                       observed_retail: float | None = None) -> dict:
    """
    Compute retail price, margin, and cost breakdown.
    - freight_multiplier: scale factor on freight mid (1.0 = baseline).
    - observed_retail: if provided (from loyalty transaction data), use as the retail price
      and compute implied margin instead of deriving retail from markup.
    """
    shrink      = shrink_override if shrink_override is not None else SHRINK_RATES.get(fruit, 0.10)
    mid_ws      = (wholesale_low + wholesale_high) / 2
    fc          = FREIGHT_COSTS.get(fruit, {"low": 0.10, "high": 0.20})
    freight_mid = ((fc["low"] + fc["high"]) / 2) * freight_multiplier
    landed_cost    = mid_ws + freight_mid
    effective_cost = landed_cost / (1 - shrink)

    if observed_retail is not None:
        retail         = observed_retail
        retail_source  = "observed"
        implied_markup = ((retail / effective_cost) - 1) * 100 if effective_cost > 0 else 0
    else:
        retail         = effective_cost * (1 + markup_pct / 100)
        retail_source  = "estimated"
        implied_markup = markup_pct

    margin = (retail - effective_cost) / retail * 100 if retail > 0 else 0

    return {
        "wholesale_mid":    round(mid_ws, 2),
        "freight_mid":      round(freight_mid, 2),
        "landed_cost":      round(landed_cost, 2),
        "effective_cost":   round(effective_cost, 2),
        "retail_price":     round(retail, 2),
        "retail_source":    retail_source,
        "implied_markup":   round(implied_markup, 1),
        "gross_margin_pct": round(margin, 1),
        "shrink_pct":       round(shrink * 100, 1),
    }
