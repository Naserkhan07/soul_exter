"""
Checkpointing — survive Kaggle session death.

The agent's position (location index, category index, HF dataset offset,
counters) is flushed to JSON after every batch, so a new session resumes
exactly where the last one stopped.
"""

import json
import logging
from datetime import datetime, timezone

import config

log = logging.getLogger("agent.checkpoint")

DEFAULT_STATE = {
    "location_index": 0,
    "category_index": 0,
    "hf_dataset_offset": 0,
    "total_candidates_processed": 0,
    "total_leads_saved": 0,
    "last_saved": None,
}


def load_checkpoint() -> dict:
    if config.CHECKPOINT_PATH.exists():
        try:
            with open(config.CHECKPOINT_PATH, encoding="utf-8") as fh:
                state = json.load(fh)
            merged = {**DEFAULT_STATE, **state}
            log.info("Resuming from checkpoint: %s", merged)
            return merged
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Bad checkpoint (%s) — starting fresh", exc)
    return dict(DEFAULT_STATE)


def save_checkpoint(state: dict) -> None:
    state = dict(state)
    state["last_saved"] = datetime.now(timezone.utc).isoformat()
    tmp = config.CHECKPOINT_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    tmp.replace(config.CHECKPOINT_PATH)
    log.debug("Checkpoint saved: %s", state)
