"""
Kroger Public API client — competitor retail pricing for Chicago-area Mariano's stores.
Mariano's is a Kroger banner, making it the most direct Chicago-area comp for Jewel-Osco.

Registration: https://developer.kroger.com  (free, 10k calls/day)
Auth: OAuth2 Client Credentials flow.
Docs: https://developer.kroger.com/documentation/api-products/public/products/overview
"""

import base64
import streamlit as st
import requests

KROGER_TOKEN_URL   = "https://api.kroger.com/v1/connect/oauth2/token"
KROGER_LOCATION_URL = "https://api.kroger.com/v1/locations"
KROGER_PRODUCT_URL  = "https://api.kroger.com/v1/products"

# Chicago-area ZIP codes to search for Mariano's locations
CHICAGO_ZIPS = ["60601", "60614", "60625", "60647", "60657"]

# Map our fruit names → search terms for Kroger product catalog
FRUIT_KROGER_MAP = {
    "Jackfruit":             ["jackfruit"],
    "Soursop (Guanábana)":  ["soursop", "guanabana"],
    "Dragonfruit (Pitaya)":  ["dragon fruit", "pitaya"],
    "Starfruit (Carambola)": ["star fruit", "carambola"],
    "Tomatillos":            ["tomatillo"],
    "Prickly Pear":          ["prickly pear", "cactus pear"],
    "Lychee":                ["lychee", "litchi"],
    "Sitafal (Sugar Apple)": ["sugar apple", "custard apple", "cherimoya"],
}


@st.cache_data(ttl=3600, show_spinner=False)
def get_kroger_token(client_id: str, client_secret: str) -> str | None:
    """Fetch an OAuth2 client credentials token. Cached for 1 hour."""
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        resp = requests.post(
            KROGER_TOKEN_URL,
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": "product.compact"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def get_marianos_location_ids(token: str) -> list[str]:
    """
    Find Mariano's store location IDs in Chicago.
    Returns a list of locationId strings (up to 5).
    """
    ids = []
    for zip_code in CHICAGO_ZIPS:
        try:
            resp = requests.get(
                KROGER_LOCATION_URL,
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/json"},
                params={"filter.zipCode": zip_code, "filter.chain": "MARIANOS",
                        "filter.radiusInMiles": "5", "filter.limit": "2"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            for loc in data:
                lid = loc.get("locationId")
                if lid and lid not in ids:
                    ids.append(lid)
            if len(ids) >= 5:
                break
        except Exception:
            continue
    return ids


@st.cache_data(ttl=86400, show_spinner=False)
def search_fruit_price(token: str, location_id: str, search_term: str) -> list[dict]:
    """Search for a product at a specific Kroger/Mariano's location and return price data."""
    try:
        resp = requests.get(
            KROGER_PRODUCT_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={
                "filter.term":       search_term,
                "filter.locationId": location_id,
                "filter.limit":      "10",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception:
        return []


def _extract_price(product: dict) -> float | None:
    """Pull the regular retail price from a Kroger product dict."""
    try:
        items = product.get("items", [])
        for item in items:
            price = item.get("price", {})
            regular = price.get("regular") or price.get("promo")
            if regular:
                return float(regular)
    except Exception:
        pass
    return None


def _is_produce(product: dict) -> bool:
    """Rough filter to skip non-produce hits (e.g. canned, frozen)."""
    desc = (product.get("description", "") + " " +
            " ".join(product.get("categories", []))).lower()
    exclude = ["canned", "frozen", "juice", "extract", "supplement",
               "dried", "candy", "jam", "jelly", "drink", "tea"]
    return not any(w in desc for w in exclude)


def get_competitor_prices(client_id: str, client_secret: str) -> tuple[dict[str, dict], str | None]:
    """
    Fetch average Chicago Mariano's retail prices for each of our fruits.
    Returns:
        prices: {fruit: {"avg": float, "min": float, "max": float,
                          "n": int, "source": "Mariano's (Chicago)"}}
        error: str | None
    """
    token = get_kroger_token(client_id, client_secret)
    if not token:
        return {}, "Could not authenticate with Kroger API — check client ID and secret."

    location_ids = get_marianos_location_ids(token)
    if not location_ids:
        return {}, "No Mariano's locations found in Chicago area."

    # Use first 3 locations to average across stores
    sample_locations = location_ids[:3]
    results = {}

    for fruit, terms in FRUIT_KROGER_MAP.items():
        prices_found = []
        for term in terms:
            for loc_id in sample_locations:
                products = search_fruit_price(token, loc_id, term)
                for p in products:
                    if _is_produce(p):
                        price = _extract_price(p)
                        if price and 0.50 < price < 50.0:
                            prices_found.append(price)
            if prices_found:
                break  # Stop at first search term that yields results

        if prices_found:
            results[fruit] = {
                "avg":    round(sum(prices_found) / len(prices_found), 2),
                "min":    round(min(prices_found), 2),
                "max":    round(max(prices_found), 2),
                "n":      len(prices_found),
                "source": "Mariano's Chicago (Kroger API)",
            }

    if not results:
        return {}, "Kroger API returned no produce prices — the stores may not carry these fruits."

    return results, None
