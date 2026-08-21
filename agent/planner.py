"""
Planner — decides WHAT to look at next.

Walks the (location x category) grid deterministically and resumably,
and interleaves other discovery sources (HF dataset batches, Reddit
signals) so no single third-party dependency can stall the whole agent.
"""

import logging

import config
from geography.loader import iter_locations

log = logging.getLogger("agent.planner")


class Planner:
    def __init__(self, checkpoint_state: dict,
                 priority_states: list | None = None,
                 categories: list | None = None):
        self.state = checkpoint_state
        self.locations = list(iter_locations(priority_states))
        self.categories = categories or config.BUSINESS_CATEGORIES

    def current_target(self) -> dict | None:
        """The (location, category) cell the agent should mine next."""
        li = self.state.get("location_index", 0)
        ci = self.state.get("category_index", 0)
        if li >= len(self.locations):
            return None  # entire grid exhausted
        return {
            "location": self.locations[li],
            "category": self.categories[ci],
        }

    def advance(self) -> None:
        """Move to next category; roll over to next location when done."""
        self.state["category_index"] = self.state.get("category_index", 0) + 1
        if self.state["category_index"] >= len(self.categories):
            self.state["category_index"] = 0
            self.state["location_index"] = self.state.get("location_index", 0) + 1
        log.info("Planner advanced to location=%s category=%s",
                 self.state["location_index"], self.state["category_index"])

    def progress(self) -> dict:
        total = len(self.locations) * len(self.categories)
        done = (self.state.get("location_index", 0) * len(self.categories)
                + self.state.get("category_index", 0))
        return {"cells_done": done, "cells_total": total,
                "percent": round(100 * done / max(total, 1), 2)}
