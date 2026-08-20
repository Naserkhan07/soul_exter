#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from pathlib import Path

REQUIRED_KEYS = {"decision", "plan", "deliverable", "validation", "distribution", "risks"}
SECRET_PATTERNS = [
    re.compile(r"rzp_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"sk-(?:live-)?[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN .*PRIVATE KEY-----"),
]


def load_jsonl(path: Path) -> list[dict]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
    return records


def validate(train_path: Path, benchmark_path: Path) -> dict:
    train = load_jsonl(train_path)
    benchmark = load_jsonl(benchmark_path)
    errors: list[str] = []
    ids = [record.get("id") for record in train]
    if len(ids) != len(set(ids)):
        errors.append("duplicate training IDs")
    prompts: list[str] = []
    categories = Counter()
    for index, record in enumerate(train):
        messages = record.get("messages")
        if not isinstance(messages, list) or [m.get("role") for m in messages] != ["system", "user", "assistant"]:
            errors.append(f"record {index}: messages must be system/user/assistant")
            continue
        categories[record.get("category", "missing")] += 1
        prompts.append(messages[1].get("content", "").strip().lower())
        try:
            answer = json.loads(messages[2].get("content", ""))
        except json.JSONDecodeError:
            errors.append(f"record {index}: assistant is not strict JSON")
            continue
        if set(answer) != REQUIRED_KEYS:
            errors.append(f"record {index}: wrong output keys")
        for key in REQUIRED_KEYS - {"decision"}:
            if not isinstance(answer.get(key), list) or not answer[key]:
                errors.append(f"record {index}: {key} must be a non-empty list")
        serialized = json.dumps(record)
        if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
            errors.append(f"record {index}: possible credential")
    if len(prompts) != len(set(prompts)):
        errors.append("duplicate training prompts")
    benchmark_prompts = [record.get("prompt", "").strip().lower() for record in benchmark]
    overlap = set(prompts) & set(benchmark_prompts)
    if overlap:
        errors.append(f"train/benchmark leakage: {len(overlap)} exact prompts")
    for index, record in enumerate(benchmark):
        if not record.get("id") or not record.get("prompt") or not record.get("required") or not record.get("forbidden"):
            errors.append(f"benchmark {index}: missing fields")
    if len(benchmark_prompts) != len(set(benchmark_prompts)):
        errors.append("duplicate benchmark prompts")
    result = {"training_records": len(train), "benchmark_records": len(benchmark),
              "categories": dict(categories), "errors": errors}
    if errors:
        raise ValueError(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    root = Path(__file__).parent
    parser.add_argument("--train", type=Path, default=root / "automaton_train.jsonl")
    parser.add_argument("--benchmark", type=Path, default=root / "automaton_benchmark.jsonl")
    args = parser.parse_args()
    print(json.dumps(validate(args.train, args.benchmark), indent=2))


if __name__ == "__main__":
    main()
