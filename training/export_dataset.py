#!/usr/bin/env python3
"""
Export Jarvis's training dataset for fine-tuning our own trading LLM
(Option C - "jarvis-trading-brain").

Produces training/jarvis_dataset.jsonl in chat-messages format combining:
  1. YOUR bot's own trade journal (from SQLite memory - every closed trade
     with regime, votes, confidence and outcome becomes a lesson)
  2. Jarvis's built-in knowledge base (rules -> instruction Q&A)
  3. Indicator & strategy reference docs

Run from the repo root:
    python training/export_dataset.py

Then open training/train_jarvis_colab.py in Google Colab (free T4 GPU),
upload jarvis_dataset.jsonl when prompted, and train.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_trader import memory, knowledge, indicators  # noqa: E402

OUT = Path(__file__).parent / "jarvis_dataset.jsonl"


def knowledge_samples():
    out = []
    section_q = {
        "market_structure": "Explain this market structure concept for a trader:",
        "indicators": "Explain this technical indicator concept:",
        "strategies": "Explain this trading strategy concept:",
        "candlestick_patterns": "Explain this candlestick pattern principle:",
        "chart_patterns": "Explain this chart pattern principle:",
        "order_flow": "Explain this order flow concept:",
        "mathematical_models": "Explain this quantitative trading concept:",
        "market_timings": "Explain this market session concept:",
        "trading_psychology": "Explain this trading psychology principle:",
        "trade_scenarios": "How should a trader handle this scenario?",
        "risk_management": "Explain this risk management rule:",
        "market_movement_causes": "Explain what moves markets:",
    }
    for section, rules in knowledge.KNOWLEDGE.items():
        q = section_q.get(section, "Explain this trading concept:")
        for rule in rules:
            head = rule.split(":")[0][:70]
            out.append({"messages": [
                {"role": "user", "content": f"{q} {head}"},
                {"role": "assistant", "content": rule}]})
    return out


def reference_samples():
    out = []
    for key, info in indicators.INDICATOR_INFO.items():
        out.append({"messages": [
            {"role": "user",
             "content": f"What is the {info['name']} and how should I use it?"},
            {"role": "assistant",
             "content": f"{info['what']} Scoring: {info['how_scored']} "
                        f"{info['detail']}"}]})
    for name, desc in indicators.STRATEGY_INFO.items():
        out.append({"messages": [
            {"role": "user", "content": f"Describe the {name} trading strategy."},
            {"role": "assistant", "content": desc}]})
    return out


def main():
    samples = []
    journal = memory.export_journal_for_training(limit=5000)
    print(f"journal samples (your bot's own trades): {len(journal)}")
    samples += journal
    ks = knowledge_samples()
    print(f"knowledge-base samples: {len(ks)}")
    samples += ks
    rs = reference_samples()
    print(f"reference samples: {len(rs)}")
    samples += rs

    with open(OUT, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(samples)} samples -> {OUT}")
    print("Next: open training/train_jarvis_colab.py in Google Colab (T4), "
          "upload this file, run all cells.")


if __name__ == "__main__":
    main()
