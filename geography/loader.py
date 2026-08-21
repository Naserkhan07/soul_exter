"""
Geography loader — systematic India-wide coverage.

India -> States/UTs -> Cities (-> localities, extendable via localities.json).
The planner walks this tree so discovery is systematic, not random.
"""

import json
import logging
from pathlib import Path

import config

log = logging.getLogger("geography")

_STATES_FILE = config.GEOGRAPHY_DIR / "india_states.json"
_LOCALITIES_FILE = config.GEOGRAPHY_DIR / "localities.json"  # optional


def load_states() -> dict:
    with open(_STATES_FILE, encoding="utf-8") as fh:
        return json.load(fh)["states"]


def load_localities() -> dict:
    """Optional {city: [locality, ...]} refinement file."""
    if Path(_LOCALITIES_FILE).exists():
        with open(_LOCALITIES_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def iter_locations(priority_states: list | None = None):
    """
    Yield location dicts in a deterministic order:
        {"state": ..., "city": ..., "locality": ..., "query_location": ...}
    Big metros first (more businesses), then the long tail.
    """
    states = load_states()
    localities = load_localities()

    ordered_states = list(states)
    if priority_states:
        ordered_states = ([s for s in priority_states if s in states]
                          + [s for s in ordered_states if s not in priority_states])

    for state in ordered_states:
        for city in states[state]:
            city_localities = localities.get(city) or [""]
            for locality in city_localities:
                place = f"{locality}, {city}" if locality else city
                yield {
                    "state": state,
                    "city": city,
                    "locality": locality,
                    "query_location": f"{place}, {state}, India",
                }


def location_count() -> int:
    return sum(1 for _ in iter_locations())
