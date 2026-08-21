"""
Hugging Face company dataset loader.

Streams SaleleadsOrg/linkedin-company-profile (~3.9M LinkedIn company
records) in batches, filtering to Indian companies BEFORE anything
reaches Qwen:

    3.9M records
      -> India filter (headquarter.country == "IN")
      -> has name (+ ideally website/location)
      -> deduplicate
      -> candidate leads

Actual dataset schema (verified 2026-08):
    id, name, universal_name, description, linkedin_url, website_url,
    followers_count, associated_members_count, verification, founded_on,
    headquarter (JSON str: {city, line1, country, geographic_area, ...}),
    location_branches (JSON list str), logo_url, specialities, industry,
    hashtags, funding_info, __created_at, __updated_at, claimable,
    company_type

Requires `datasets` (pip install datasets). Optional — without it the
agent uses other discovery sources.
"""

import json
import logging
import re

import config

log = logging.getLogger("tools.huggingface")

INDIA_MARKERS = re.compile(
    r"\b(india|maharashtra|karnataka|telangana|tamil ?nadu|gujarat|"
    r"rajasthan|kerala|punjab|haryana|delhi|mumbai|bengaluru|bangalore|"
    r"hyderabad|chennai|kolkata|pune|ahmedabad|jaipur|lucknow|surat|noida|"
    r"gurgaon|gurugram|indore|nagpur|bhopal|kochi|coimbatore|chandigarh|"
    r"visakhapatnam|vadodara)\b", re.I)


def _parse_json_field(value):
    """Dataset stores nested objects as JSON strings — parse defensively."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _headquarter(record: dict) -> dict:
    return _parse_json_field(record.get("headquarter"))


def is_indian(record: dict) -> bool:
    hq = _headquarter(record)
    country = (hq.get("country") or "").upper()
    if country == "IN":
        return True
    if country and country != "IN":
        return False
    # no headquarter country -> fall back to text markers
    blob = " ".join(str(record.get(k) or "") for k in
                    ("headquarter", "location_branches", "name"))
    return bool(INDIA_MARKERS.search(blob))


def normalize_record(record: dict) -> dict:
    hq = _headquarter(record)
    city = hq.get("city") or ""
    state = hq.get("geographic_area") or ""
    parts = [p for p in (city, state, "India") if p]

    linkedin = record.get("linkedin_url") or ""
    if "linkedin.com" not in linkedin:
        linkedin = ""

    return {
        "source": "hf_dataset",
        "business_name": (record.get("name") or "").strip(),
        "business_category": (record.get("industry") or "").strip(),
        "address": ", ".join(parts),
        "website": (record.get("website_url") or "").strip(),
        "linkedin": linkedin,
        "company_size": str(record.get("followers_count") or ""),
        "source_url": linkedin or (record.get("website_url") or ""),
        "location_meta": {
            "state": state,
            "city": city,
            "locality": "",
            "query_location": ", ".join(parts),
        },
    }


def iter_india_companies(limit: int = 1000, skip: int = 0,
                         dataset_id: str | None = None):
    """
    Stream the dataset and yield normalized Indian company candidates.
    `skip` allows resuming from a checkpoint offset (rows scanned so far).
    """
    try:
        from datasets import load_dataset
    except ImportError:
        log.warning("`datasets` not installed — HF discovery disabled "
                    "(pip install datasets)")
        return

    dataset_id = dataset_id or config.HF_COMPANY_DATASET
    log.info("Streaming %s (skip=%d, limit=%d)", dataset_id, skip, limit)
    try:
        ds = load_dataset(dataset_id, split="train", streaming=True)
        if skip:
            ds = ds.skip(skip)
    except Exception as exc:
        log.warning("Could not open dataset %s: %s", dataset_id, exc)
        return

    yielded = 0
    scanned = skip
    for record in ds:
        scanned += 1
        if not isinstance(record, dict):
            continue
        if not is_indian(record):
            continue
        cand = normalize_record(record)
        if not cand["business_name"]:
            continue
        # prefer investigable candidates: need a website or a LinkedIn URL
        if not cand["website"] and not cand["linkedin"]:
            continue
        cand["_dataset_offset"] = scanned
        yield cand
        yielded += 1
        if yielded >= limit:
            break
    log.info("HF dataset: yielded %d Indian companies (scanned up to row %d)",
             yielded, scanned)


def dump_batch_to_file(limit: int = 1000, skip: int = 0) -> str:
    """Convenience: write a filtered batch to data/processed for inspection."""
    out_path = config.PROCESSED_DIR / f"hf_india_batch_{skip}_{skip + limit}.jsonl"
    n = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for cand in iter_india_companies(limit=limit, skip=skip):
            fh.write(json.dumps(cand, ensure_ascii=False) + "\n")
            n += 1
    log.info("Wrote %d records to %s", n, out_path)
    return str(out_path)
