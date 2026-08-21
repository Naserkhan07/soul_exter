"""
Hugging Face company dataset loader.

Streams SalaleadsOrg/linkedin-company-profile (or any compatible company
dataset) in batches, filtering to Indian companies with usable signals
BEFORE anything reaches Qwen:

    millions of records
      -> India filter
      -> has name (+ ideally website/location)
      -> deduplicate
      -> candidate leads

Requires `datasets` (pip install datasets). Optional — without it the
agent uses other discovery sources.
"""

import json
import logging
import re

import config

log = logging.getLogger("tools.huggingface")

INDIA_MARKERS = re.compile(
    r"\b(india|bharat|maharashtra|karnataka|telangana|tamil ?nadu|gujarat|"
    r"rajasthan|kerala|punjab|haryana|delhi|mumbai|bengaluru|bangalore|"
    r"hyderabad|chennai|kolkata|pune|ahmedabad|jaipur|lucknow|surat|noida|"
    r"gurgaon|gurugram|indore|nagpur|bhopal|kochi|coimbatore|chandigarh|"
    r"visakhapatnam|vadodara)\b", re.I)

# common field aliases across LinkedIn-style company datasets
NAME_KEYS = ("name", "company_name", "company", "title")
LOCATION_KEYS = ("location", "headquarters", "hq", "address", "country",
                 "locality", "region", "geo")
WEBSITE_KEYS = ("website", "url", "company_website", "domain", "site")
INDUSTRY_KEYS = ("industry", "industries", "category", "sector")
LINKEDIN_KEYS = ("linkedin_url", "linkedin", "profile_url", "li_url", "url")
SIZE_KEYS = ("company_size", "size", "employees", "employee_count", "staff_count")


def _first(record: dict, keys) -> str:
    for k in keys:
        v = record.get(k)
        if v:
            return str(v)
    return ""


def is_indian(record: dict) -> bool:
    blob = " ".join(str(record.get(k, "")) for k in
                    ("location", "headquarters", "hq", "address", "country",
                     "locality", "region", "geo", "name"))
    return bool(INDIA_MARKERS.search(blob))


def normalize_record(record: dict) -> dict:
    linkedin = _first(record, LINKEDIN_KEYS)
    if "linkedin.com" not in linkedin:
        linkedin = ""
    return {
        "source": "hf_dataset",
        "business_name": _first(record, NAME_KEYS),
        "business_category": _first(record, INDUSTRY_KEYS),
        "address": _first(record, LOCATION_KEYS),
        "website": _first(record, WEBSITE_KEYS),
        "linkedin": linkedin,
        "company_size": _first(record, SIZE_KEYS),
        "source_url": linkedin or _first(record, WEBSITE_KEYS),
    }


def iter_india_companies(limit: int = 1000, skip: int = 0,
                         dataset_id: str | None = None):
    """
    Stream the dataset and yield normalized Indian company candidates.
    `skip` allows resuming from a checkpoint offset.
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
    except Exception as exc:
        log.warning("Could not open dataset %s: %s", dataset_id, exc)
        return

    yielded = scanned = 0
    for record in ds:
        scanned += 1
        if scanned <= skip:
            continue
        if not isinstance(record, dict):
            continue
        if not is_indian(record):
            continue
        cand = normalize_record(record)
        if not cand["business_name"]:
            continue
        cand["_dataset_offset"] = scanned
        yield cand
        yielded += 1
        if yielded >= limit:
            break
    log.info("HF dataset: yielded %d Indian companies from %d scanned",
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
