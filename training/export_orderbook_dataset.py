#!/usr/bin/env python3
"""
Export ORDER-BOOK -> Qwen training dataset (chat format).

Turns the micro recorder's data into LLM fine-tuning samples where the
model sees a TEXT RENDERING of the market microstructure state and must
answer in the strict structured format:

    SIGNAL: BUY | SELL | NO TRADE
    ENTRY: <price>
    TP: <price>
    SL: <price>
    CONFIDENCE: <percent>
    REASON: <one line grounded in the given evidence>

Labels come from REAL triple-barrier outcomes (never invented):
  - BUY sample  when the buy-side TP hit before SL within the horizon
  - SELL sample when the sell side won
  - NO TRADE    when neither offered the R:R (also trained on ambiguous chop
                - the "when NOT to trade" cases, deliberately oversampled)

Usage (after the recorder has collected data):
    python training/export_orderbook_dataset.py BTCUSDT
    -> training/orderbook_dataset.jsonl

Then train on free GPU with training/train_qwen_orderbook.py (Colab/Kaggle).
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_trader import config                       # noqa: E402
from jarvis_trader.micro import microfeatures, labeler  # noqa: E402

MICRO_DIR = config.DATA_DIR / "micro"
OUT = Path(__file__).parent / "orderbook_dataset.jsonl"

SYSTEM = (
    "You are MICRO-JARVIS, a market-microstructure trading model. "
    "You receive order-book and trade-flow evidence for one moment in time. "
    "Decide BUY, SELL or NO TRADE. Reply ONLY in this exact format:\n"
    "SIGNAL: <BUY|SELL|NO TRADE>\nENTRY: <price or ->\nTP: <price or ->\n"
    "SL: <price or ->\nCONFIDENCE: <0-100>%\nREASON: <one short line>. "
    "Prefer NO TRADE unless the evidence is strong."
)


def render_market_state(r):
    """Human/LLM-readable rendering of one feature row (the model input)."""
    lines = [f"MARKET STATE @ mid {r['mid']:.2f}"]
    lines.append(f"Order-book imbalance  L1 {r['imb_l1']:+.3f}  "
                 f"L5 {r['imb_l5']:+.3f}  L10 {r['imb_l10']:+.3f}  "
                 f"L20 {r['imb_l20']:+.3f}")
    lines.append(f"Spread {r['spread_bps']:.2f} bps | microprice "
                 f"{r['micro_dist_bps']:+.2f} bps | depth ratio "
                 f"{r['depth_ratio']:.2f}")
    lines.append(f"Trade delta  1s {r['delta_1s']:+.2f}  5s {r['delta_5s']:+.2f} "
                 f" 10s {r['delta_10s']:+.2f}  30s {r['delta_30s']:+.2f}")
    lines.append(f"Volume 5s {r['vol_5s']:.2f} | 30s {r['vol_30s']:.2f} | "
                 f"intensity {r['trade_intensity']:.1f}/s | large-trade share "
                 f"{r['large_trade_ratio']:.2f}")
    lines.append(f"Bid cancel-rate {r['bid_cancel_rate']:.2f} add-rate "
                 f"{r['bid_add_rate']:.3f} | Ask cancel-rate "
                 f"{r['ask_cancel_rate']:.2f} add-rate {r['ask_add_rate']:.3f}")
    lines.append(f"Absorption {r['absorption']:.2f} | liquidity consumed 10s "
                 f"{r['liq_consumed_10s']:.2f}")
    lines.append(f"Returns  1s {r['ret_1s_bps']:+.2f}  5s {r['ret_5s_bps']:+.2f} "
                 f" 30s {r['ret_30s_bps']:+.2f} bps | realized vol "
                 f"{r['rvol_1m_bps']:.2f} bps | accel {r['accel_bps']:+.2f}")
    if r.get("liq_buy_30s") or r.get("liq_sell_30s"):
        lines.append(f"Liquidations 30s  long {r['liq_sell_30s']:.0f}  "
                     f"short {r['liq_buy_30s']:.0f}")
    if r.get("funding_bps"):
        lines.append(f"Funding {r['funding_bps']:+.2f} bps | OI 5m change "
                     f"{r.get('oi_chg_5m', 0):+.1f} bps")
    lines.append("Decision?")
    return "\n".join(lines)


def _reason(r, y):
    """Evidence-grounded one-liner (no invented facts)."""
    bits = []
    if y == 2:
        if r["imb_l5"] > 0.1:
            bits.append("bid-side book imbalance")
        if r["delta_5s"] > 0.1:
            bits.append("aggressive buying flow")
        if r["ask_cancel_rate"] > 0.5:
            bits.append("ask liquidity pulling")
        if r["absorption"] > 2 and r["delta_5s"] < 0:
            bits.append("sell pressure being absorbed")
        return ("Bullish: " + ", ".join(bits)) if bits else \
            "Bullish evidence outweighs; flow and book lean up"
    if y == 0:
        if r["imb_l5"] < -0.1:
            bits.append("ask-side book imbalance")
        if r["delta_5s"] < -0.1:
            bits.append("aggressive selling flow")
        if r["bid_cancel_rate"] > 0.5:
            bits.append("bid liquidity pulling")
        return ("Bearish: " + ", ".join(bits)) if bits else \
            "Bearish evidence outweighs; flow and book lean down"
    if abs(r["imb_l5"]) < 0.08 and abs(r["delta_5s"]) < 0.08:
        return "No edge: balanced book and neutral flow"
    return "Conflicting evidence; risk/reward not attractive"


def make_sample(r):
    y = r["y"]
    entry = r["mid"]
    tp_bps, sl_bps = r["tp_bps"], r["sl_bps"]
    conf_hi = random.randint(78, 92)
    conf_lo = random.randint(55, 74)
    if y == 2:
        ans = (f"SIGNAL: BUY\nENTRY: {entry:.2f}\n"
               f"TP: {entry * (1 + tp_bps / 1e4):.2f}\n"
               f"SL: {entry * (1 - sl_bps / 1e4):.2f}\n"
               f"CONFIDENCE: {conf_hi}%\nREASON: {_reason(r, y)}")
    elif y == 0:
        ans = (f"SIGNAL: SELL\nENTRY: {entry:.2f}\n"
               f"TP: {entry * (1 - tp_bps / 1e4):.2f}\n"
               f"SL: {entry * (1 + sl_bps / 1e4):.2f}\n"
               f"CONFIDENCE: {conf_hi}%\nREASON: {_reason(r, y)}")
    else:
        ans = (f"SIGNAL: NO TRADE\nENTRY: -\nTP: -\nSL: -\n"
               f"CONFIDENCE: {conf_lo}%\nREASON: {_reason(r, y)}")
    return {"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": render_market_state(r)},
        {"role": "assistant", "content": ans}]}


def main():
    symbols = [s.upper() for s in sys.argv[1:] if not s.startswith("-")] \
        or ["BTCUSDT"]
    all_samples = []
    for sym in symbols:
        feat = MICRO_DIR / f"{sym}_features.jsonl"
        lab = MICRO_DIR / f"{sym}_labeled.jsonl"
        if not feat.exists():
            print(f"[export] building features for {sym}...")
            microfeatures.build(sym)
        if not lab.exists():
            print(f"[export] labeling {sym}...")
            labeler.label(sym)
        if not lab.exists():
            print(f"[export] no data for {sym} - run the recorder first:")
            print(f"         python -m jarvis_trader.micro.recorder {sym}")
            continue
        rows = [json.loads(l) for l in open(lab, encoding="utf-8")]
        buys = [r for r in rows if r["y"] == 2]
        sells = [r for r in rows if r["y"] == 0]
        notrades = [r for r in rows if r["y"] == 1]
        # balance: all directional samples + up to 1.5x that many NO-TRADEs
        # (keeps "when NOT to trade" strongly represented but not drowning)
        random.seed(42)
        random.shuffle(notrades)
        keep_nt = notrades[:int(1.5 * max(len(buys) + len(sells), 50))]
        chosen = buys + sells + keep_nt
        random.shuffle(chosen)
        all_samples += [make_sample(r) for r in chosen]
        print(f"[export] {sym}: BUY {len(buys)} SELL {len(sells)} "
              f"NO-TRADE kept {len(keep_nt)}")

    with open(OUT, "w", encoding="utf-8") as f:
        for s in all_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"\n[export] wrote {len(all_samples)} samples -> {OUT}")
    print("[export] next: upload to Colab/Kaggle and run "
          "training/train_qwen_orderbook.py on a free T4 GPU")


if __name__ == "__main__":
    main()
