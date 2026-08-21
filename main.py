#!/usr/bin/env python3
"""
India Client-Finding Agent — CLI entry point.

  python main.py run                 # full autonomous loop (discover -> qualify -> save)
  python main.py run --max 100       # cap candidates this session
  python main.py run --states "Maharashtra,Telangana"
  python main.py demo                # investigate a few seed websites end-to-end
  python main.py seed seeds.json     # investigate candidates from a JSON file
  python main.py export              # write output/india_leads.xlsx
  python main.py export --min-score 70
  python main.py stats               # database + checkpoint status

The agent researches and saves leads. It never contacts anyone.
"""

import argparse
import json
import logging
import sys

import config


def setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        ],
    )


DEMO_CANDIDATES = [
    {
        "source": "manual",
        "business_name": "Example Cafe",
        "business_category": "restaurant",
        "website": "https://example.com",
        "address": "Pune, Maharashtra",
        "location_meta": {"state": "Maharashtra", "city": "Pune",
                          "locality": "", "query_location": "Pune, Maharashtra, India"},
        "rating": 4.3,
        "review_count": 212,
        "source_url": "https://example.com",
    },
]


def cmd_run(args):
    from agent.loop import AgentLoop

    states = [s.strip() for s in (args.states or "").split(",") if s.strip()]
    categories = [c.strip() for c in (args.categories or "").split(",") if c.strip()]
    loop = AgentLoop(
        priority_states=states or None,
        categories=categories or None,
        use_maps=not args.no_maps,
        use_hf=not args.no_hf,
        use_reddit=not args.no_reddit,
    )
    summary = loop.run(max_candidates=args.max)
    print(json.dumps(summary, indent=2, default=str))
    print("\nDone. Export the Excel file with:  python main.py export")


def cmd_seed(args):
    from agent.loop import AgentLoop

    with open(args.file, encoding="utf-8") as fh:
        candidates = json.load(fh)
    if isinstance(candidates, dict):
        candidates = [candidates]
    loop = AgentLoop(use_maps=False, use_hf=False, use_reddit=False)
    summary = loop.run(max_candidates=len(candidates),
                       extra_candidates=candidates)
    print(json.dumps(summary, indent=2, default=str))


def cmd_demo(args):
    from agent.loop import AgentLoop

    print("Demo: investigating seed candidates with backend "
          f"'{config.BRAIN_BACKEND}' ...\n")
    loop = AgentLoop(use_maps=False, use_hf=False, use_reddit=False)
    summary = loop.run(max_candidates=len(DEMO_CANDIDATES),
                       extra_candidates=list(DEMO_CANDIDATES))
    print(json.dumps(summary, indent=2, default=str))
    from export.excel import export_to_excel
    path = export_to_excel()
    print(f"\nDemo Excel written to {path}")


def cmd_export(args):
    from export.excel import export_to_excel

    path = export_to_excel(min_score=args.min_score)
    print(f"Exported to {path}")


def cmd_stats(args):
    from database.database import LeadDatabase
    from agent.checkpoint import load_checkpoint

    db = LeadDatabase()
    print(json.dumps({
        "database": db.stats(),
        "checkpoint": load_checkpoint(),
        "brain_backend": config.BRAIN_BACKEND,
    }, indent=2, default=str))


def build_parser():
    p = argparse.ArgumentParser(description="India Client-Finding Agent")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="autonomous discovery loop")
    run.add_argument("--max", type=int, default=None,
                     help="max candidates this session")
    run.add_argument("--states", help="comma-separated priority states")
    run.add_argument("--categories", help="comma-separated categories")
    run.add_argument("--no-maps", action="store_true")
    run.add_argument("--no-hf", action="store_true")
    run.add_argument("--no-reddit", action="store_true")
    run.set_defaults(func=cmd_run)

    seed = sub.add_parser("seed", help="investigate candidates from JSON file")
    seed.add_argument("file")
    seed.set_defaults(func=cmd_seed)

    demo = sub.add_parser("demo", help="end-to-end demo with sample seeds")
    demo.set_defaults(func=cmd_demo)

    exp = sub.add_parser("export", help="export leads to Excel")
    exp.add_argument("--min-score", type=int, default=0)
    exp.set_defaults(func=cmd_export)

    stats = sub.add_parser("stats", help="show database/checkpoint status")
    stats.set_defaults(func=cmd_stats)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    setup_logging(args.verbose)
    args.func(args)
