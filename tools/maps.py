"""
Google Maps discovery — via the official Places API (New).

We deliberately use Google's permitted API rather than scraping Maps.
The API has a free monthly credit but is NOT unlimited, so this tool is
optional and replaceable: without a key it simply reports 'not configured'
and the agent continues with other sources (HF dataset, web, manual seeds).

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
"""

import logging

import requests

import config

log = logging.getLogger("tools.maps")

_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
_FIELDS = ",".join([
    "places.displayName",
    "places.formattedAddress",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.googleMapsUri",
    "places.primaryTypeDisplayName",
])


def is_configured() -> bool:
    return bool(config.GOOGLE_MAPS_API_KEY)


def search_maps(category: str, location: str,
                max_results: int | None = None) -> list:
    """
    Text search e.g. ('dental clinic', 'Pune, Maharashtra, India').
    Returns a list of normalized candidate dicts.
    """
    if not is_configured():
        log.info("Google Maps API key not set — maps discovery disabled")
        return []

    max_results = max_results or config.MAX_CANDIDATES_PER_QUERY
    try:
        resp = requests.post(
            _ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": _FIELDS,
            },
            json={
                "textQuery": f"{category} in {location}",
                "maxResultCount": min(max_results, 20),
                "regionCode": "IN",
            },
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        places = resp.json().get("places", [])
    except requests.RequestException as exc:
        log.warning("Maps search failed: %s", exc)
        return []

    candidates = []
    for p in places:
        candidates.append({
            "source": "maps",
            "business_name": (p.get("displayName") or {}).get("text", ""),
            "business_category":
                (p.get("primaryTypeDisplayName") or {}).get("text", category),
            "address": p.get("formattedAddress", ""),
            "phone": p.get("internationalPhoneNumber", ""),
            "website": p.get("websiteUri", ""),
            "rating": p.get("rating"),
            "review_count": p.get("userRatingCount"),
            "google_maps": p.get("googleMapsUri", ""),
            "source_url": p.get("googleMapsUri", ""),
        })
    log.info("Maps: %d candidates for '%s in %s'",
             len(candidates), category, location)
    return candidates
