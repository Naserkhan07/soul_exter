#!/usr/bin/env python3
"""
Diagnose why the agent produces no leads.

Run on Kaggle (or anywhere):

    !python diagnose.py

Tests every part of the pipeline independently and prints PASS/FAIL with
the actual error, so you can see exactly which source is broken.
"""

import json
import sys
import traceback

OK = "✅ PASS"
BAD = "❌ FAIL"
WARN = "⚠️  WARN"

results = {}


def section(name):
    print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")


# ---------------------------------------------------------------- 1. internet
section("1. Basic internet access")
try:
    import requests
    r = requests.get("https://example.com", timeout=15)
    print(f"{OK}  example.com -> HTTP {r.status_code}")
    results["internet"] = True
except Exception as e:
    print(f"{BAD}  no internet: {type(e).__name__}: {e}")
    print("     -> Kaggle: right sidebar -> Session options -> Internet ON")
    results["internet"] = False

# ------------------------------------------------------- 2. duckduckgo search
section("2. Web search (keyless DuckDuckGo)")
try:
    from tools.web_search import search_web
    hits = search_web("dental clinic in Hyderabad Telangana India", 5)
    if hits:
        print(f"{OK}  {len(hits)} results, e.g.: {hits[0]['title'][:60]}")
        print(f"      url: {hits[0]['url'][:70]}")
        results["web_search"] = True
    else:
        print(f"{BAD}  0 results (DDG may be rate-limiting this IP)")
        results["web_search"] = False
except Exception as e:
    print(f"{BAD}  {type(e).__name__}: {e}")
    results["web_search"] = False

# --------------------------------------------------------------- 3. reddit
section("3. Reddit public JSON (keyless)")
try:
    from tools.reddit import _public_search
    posts = _public_search("need help website india", 3)
    if posts:
        print(f"{OK}  {len(posts)} posts, e.g.: {posts[0]['title'][:60]}")
        results["reddit"] = True
    else:
        print(f"{WARN}  0 posts (Reddit may block datacenter IPs — not fatal)")
        results["reddit"] = False
except Exception as e:
    print(f"{BAD}  {type(e).__name__}: {e}")
    results["reddit"] = False

# ------------------------------------------------------------ 4. HF dataset
section("4. Hugging Face company dataset")
try:
    from datasets import load_dataset
    import config
    print(f"dataset: {config.HF_COMPANY_DATASET}")
    ds = load_dataset(config.HF_COMPANY_DATASET, split="train", streaming=True)
    first = next(iter(ds))
    print(f"{OK}  streamed 1 record. Fields: {list(first.keys())[:15]}")
    print("     sample:", json.dumps(
        {k: str(v)[:60] for k, v in list(first.items())[:6]},
        indent=2, ensure_ascii=False))
    results["hf_stream"] = True

    # does the India filter + field mapping actually yield candidates?
    from tools.huggingface import iter_india_companies
    got = list(iter_india_companies(limit=3))
    if got:
        print(f"{OK}  India filter yielded {len(got)} candidates, e.g.:")
        print("     ", json.dumps(got[0], ensure_ascii=False)[:200])
        results["hf_filter"] = True
    else:
        print(f"{BAD}  India filter yielded 0 from the first pass —")
        print("     field names in the dataset probably don't match the")
        print("     aliases in tools/huggingface.py. PASTE THE 'Fields:'")
        print("     LINE ABOVE TO THE ASSISTANT so it can patch the mapping.")
        results["hf_filter"] = False
except ImportError:
    print(f"{BAD}  `datasets` not installed -> !pip install datasets")
    results["hf_stream"] = False
except Exception as e:
    print(f"{BAD}  {type(e).__name__}: {e}")
    if "401" in str(e) or "gated" in str(e).lower() or "403" in str(e):
        print("     -> dataset is gated: accept terms on its HF page and add")
        print("        an HF_TOKEN secret, then re-run.")
    results["hf_stream"] = False

# ------------------------------------------------------------------ 5. brain
section("5. Brain")
try:
    import config
    from brain.qwen import get_brain
    brain = get_brain()
    print(f"backend requested: {config.BRAIN_BACKEND}")
    print(f"active brain: {type(brain).__name__}")
    from brain.decision_engine import DecisionEngine
    q = DecisionEngine(brain).qualify({
        "business_name": "Test Co", "website": "https://t.example",
        "website_analysis": {"reachable": True, "https": False,
                             "mobile_friendly": False, "title": "",
                             "meta_description": "", "h1_count": 0,
                             "word_count": 50, "has_cta": False},
        "social": {"profiles_found": 0},
        "signals": {"rating": 4.5, "review_count": 100},
        "contacts": {"phone": "x", "email": "", "whatsapp": "",
                     "linkedin": "", "website": "x"},
    })
    print(f"{OK}  qualification works: score={q.lead_score} "
          f"qualified={q.qualified}")
    results["brain"] = True
except Exception as e:
    print(f"{BAD}  {type(e).__name__}: {e}")
    traceback.print_exc()
    results["brain"] = False

# ------------------------------------------------------------------ 6. state
section("6. Database / checkpoint state")
try:
    from database.database import LeadDatabase
    from agent.checkpoint import load_checkpoint
    db = LeadDatabase()
    print("db stats:", db.stats())
    print("checkpoint:", load_checkpoint())
    results["db"] = True
except Exception as e:
    print(f"{BAD}  {type(e).__name__}: {e}")
    results["db"] = False

# ---------------------------------------------------------------- summary
section("SUMMARY")
for key, ok in results.items():
    print(f"  {'✅' if ok else '❌'} {key}")
discovery_ok = results.get("web_search") or results.get("hf_filter") \
    or results.get("reddit")
if not discovery_ok:
    print("\n>>> ROOT CAUSE: no discovery source is producing candidates.")
    print(">>> That is why 0 leads were saved. Fix the ❌ items above,")
    print(">>> or paste this whole output to the assistant.")
else:
    print("\n>>> At least one discovery source works. If you still get no")
    print(">>> leads, paste this output + the run log to the assistant.")
