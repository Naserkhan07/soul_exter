#!/usr/bin/env python3
"""
Kaggle GPU batch runner — Phase 1 + batch qualification.

Copy this repo into a Kaggle notebook (GPU T4 x1 is enough for Qwen 2.5 3B
in 4-bit), then run this script. It:

  1. loads Qwen 2.5 3B Instruct (4-bit) as the brain
  2. resumes from data/checkpoints/agent_checkpoint.json
  3. processes a bounded batch of candidates
  4. saves leads to data/leads.db and refreshes the checkpoint
  5. exports output/india_leads.xlsx

If the Kaggle session dies, nothing is lost: persist the repo folder
(or at least data/ + output/) as a Kaggle Dataset between sessions and
the next run continues where this one stopped.

Notebook cell to prepare the environment:

    !pip -q install transformers accelerate bitsandbytes datasets \
                    requests beautifulsoup4 lxml openpyxl

Then:

    !python kaggle/run_qwen_batch.py --max 200
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force the real Qwen brain on Kaggle
os.environ.setdefault("BRAIN_BACKEND", "transformers")
os.environ.setdefault("QWEN_MODEL_ID", "Qwen/Qwen2.5-3B-Instruct")
os.environ.setdefault("QWEN_LOAD_IN_4BIT", "1")

import config  # noqa: E402
from main import setup_logging  # noqa: E402


def assert_qwen_loaded(allow_fallback: bool):
    """Make sure the REAL Qwen brain is active (not the heuristic fallback)."""
    try:
        import torch
        print(f"CUDA available: {torch.cuda.is_available()}"
              + (f" ({torch.cuda.get_device_name(0)})"
                 if torch.cuda.is_available() else ""))
    except ImportError:
        print("torch not installed!")

    from brain.qwen import get_brain, TransformersBrain

    brain = get_brain()
    if isinstance(brain, TransformersBrain):
        print(f"✅ Qwen brain active: {config.QWEN_MODEL_ID} "
              f"(4-bit={config.QWEN_LOAD_IN_4BIT})")
        return
    msg = ("❌ Qwen did NOT load — running on the heuristic fallback.\n"
           "   On Kaggle: Settings → Accelerator = GPU T4, Internet = ON, then\n"
           "   !pip install transformers accelerate bitsandbytes torch")
    if allow_fallback:
        print(msg + "\n   Continuing anyway (--allow-fallback).")
    else:
        raise SystemExit(msg)


def smoke_test_brain():
    """Phase 1 check: Input -> Qwen -> structured JSON."""
    from brain.decision_engine import DecisionEngine

    engine = DecisionEngine()
    evidence = {
        "business_name": "ABC Furniture",
        "business_category": "furniture store",
        "location": "Pune, Maharashtra",
        "website": "https://abc-furniture.example",
        "website_analysis": {
            "reachable": True, "https": False, "mobile_friendly": False,
            "title": "", "meta_description": "", "h1_count": 0,
            "word_count": 90, "outdated_design": True, "has_cta": False,
            "load_time_seconds": 6.2,
        },
        "website_issues": ["no HTTPS", "no mobile viewport", "missing <title>",
                           "thin content", "outdated design markers"],
        "social": {"profiles_found": 1, "platforms": ["instagram"],
                   "inactive": True},
        "signals": {"rating": 4.3, "review_count": 312},
        "contacts": {"phone": "present", "email": "", "whatsapp": "",
                     "linkedin": "", "website": "x"},
    }
    result = engine.qualify(evidence)
    print("=== Qwen smoke test ===")
    print(json.dumps(result.to_dict(), indent=2))
    assert 0 <= result.lead_score <= 100
    print("Smoke test OK — structured JSON verified.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200,
                    help="candidates to process this session")
    ap.add_argument("--skip-smoke-test", action="store_true")
    ap.add_argument("--no-hf", action="store_true")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="continue with heuristic brain if Qwen fails to load")
    args = ap.parse_args()

    setup_logging()

    assert_qwen_loaded(args.allow_fallback)
    if not args.skip_smoke_test:
        smoke_test_brain()

    from agent.loop import AgentLoop
    from export.excel import export_to_excel

    loop = AgentLoop(use_hf=not args.no_hf,
                     use_reddit=bool(config.REDDIT_CLIENT_ID))
    summary = loop.run(max_candidates=args.max)
    print(json.dumps(summary, indent=2, default=str))

    path = export_to_excel()
    print(f"\nExcel exported: {path}")
    print("Persist data/ and output/ as a Kaggle Dataset to resume next session.")


if __name__ == "__main__":
    main()
