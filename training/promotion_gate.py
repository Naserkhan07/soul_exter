#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote a trained adapter only when held-out evidence improves.")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--minimum", type=float, default=75.0)
    parser.add_argument("--improvement", type=float, default=2.0)
    args = parser.parse_args()
    base = json.loads(args.base.read_text())
    candidate = json.loads(args.candidate.read_text())
    reasons = []
    if candidate["average_score"] < args.minimum:
        reasons.append(f"candidate score {candidate['average_score']} < minimum {args.minimum}")
    if candidate["average_score"] < base["average_score"] + args.improvement:
        reasons.append(f"candidate did not improve base by {args.improvement} points")
    if candidate.get("safety_failures", 0):
        reasons.append(f"candidate has {candidate['safety_failures']} safety failures")
    decision = {"promote": not reasons, "base_score": base["average_score"],
                "candidate_score": candidate["average_score"], "reasons": reasons}
    print(json.dumps(decision, indent=2))
    raise SystemExit(0 if decision["promote"] else 1)


if __name__ == "__main__":
    main()
