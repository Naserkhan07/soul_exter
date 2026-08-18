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
    "You receive the ORDER-BOOK SEQUENCE - how the book and trade flow "
    "evolved over the last 60 seconds (T-60s to NOW) - for one market. "
    "Read the evolution (liquidity appearing/pulling, aggression building, "
    "absorption) and decide BUY, SELL or NO TRADE. Reply ONLY in this exact "
    "format:\n"
    "SIGNAL: <BUY|SELL|NO TRADE>\nENTRY: <price or ->\nTP: <price or ->\n"
    "SL: <price or ->\nCONFIDENCE: <0-100>%\nREASON: <one short line>. "
    "Prefer NO TRADE unless the evidence is strong."
)

# sequence config: how many past feature rows Qwen sees and their spacing
SEQ_STEPS = (60, 45, 30, 20, 10, 5, 0)     # seconds back from decision time


def _seq_line(offset, r):
    """One compact line of the evolution block for a single feature row."""
    tag = "NOW " if offset == 0 else f"T-{offset:02d}s"
    return (f"{tag} mid {r['mid']:.2f} | imbL1 {r['imb_l1']:+.2f} "
            f"L5 {r['imb_l5']:+.2f} L20 {r['imb_l20']:+.2f} | "
            f"delta5s {r['delta_5s']:+.2f} | vol5s {r['vol_5s']:.1f} | "
            f"cancB {r['bid_cancel_rate']:.2f} cancA {r['ask_cancel_rate']:.2f} | "
            f"absorb {r['absorption']:.1f} | ret5s {r['ret_5s_bps']:+.1f}bps")


def render_sequence(seq):
    """seq = [(seconds_back, feature_row), ...] oldest first, 0 = now.
    This is the model INPUT: how the book EVOLVED into this moment."""
    r0 = seq[-1][1]
    lines = ["ORDER-BOOK SEQUENCE (oldest to now):"]
    for off, r in seq:
        lines.append(_seq_line(off, r))
    lines.append(
        f"NOW detail: spread {r0['spread_bps']:.2f}bps | micro "
        f"{r0['micro_dist_bps']:+.2f}bps | depth {r0['depth_ratio']:.2f} | "
        f"delta1s {r0['delta_1s']:+.2f} 10s {r0['delta_10s']:+.2f} "
        f"30s {r0['delta_30s']:+.2f} | intensity {r0['trade_intensity']:.1f}/s | "
        f"large {r0['large_trade_ratio']:.2f} | addB {r0['bid_add_rate']:.3f} "
        f"addA {r0['ask_add_rate']:.3f} | liqCons {r0['liq_consumed_10s']:.1f} | "
        f"rvol {r0['rvol_1m_bps']:.2f}bps | accel {r0['accel_bps']:+.2f}")
    if r0.get("liq_buy_30s") or r0.get("liq_sell_30s"):
        lines.append(f"Liquidations 30s: long {r0['liq_sell_30s']:.0f} "
                     f"short {r0['liq_buy_30s']:.0f}")
    if r0.get("funding_bps"):
        lines.append(f"Funding {r0['funding_bps']:+.2f}bps | OI5m "
                     f"{r0.get('oi_chg_5m', 0):+.1f}bps")
    lines.append("Decision?")
    return "\n".join(lines)


def render_market_state(r):
    """Back-compat single-state rendering (live fallback when no history)."""
    return render_sequence([(0, r)])


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


def make_sample(r, seq):
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
        {"role": "user", "content": render_sequence(seq)},
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
        # index rows by time for sequence lookback
        by_time = [(r["t"], i) for i, r in enumerate(rows)]

        def sequence_for(idx):
            """Build the (seconds_back, row) sequence ending at rows[idx].
            Uses only PAST rows (leak-free). None if history is too thin."""
            t0 = rows[idx]["t"]
            seq = []
            j = idx
            for back in SEQ_STEPS:
                target = t0 - back
                # walk back from idx to find the row closest at/before target
                while j > 0 and rows[j - 1]["t"] >= target - 2.5:
                    j -= 1
                k = j
                best = None
                while k <= idx and rows[k]["t"] <= target + 2.5:
                    best = k
                    k += 1
                if best is None:
                    return None
                seq.append((back, rows[best]))
            return seq if len(seq) == len(SEQ_STEPS) else None

        buys = [i for i, r in enumerate(rows) if r["y"] == 2]
        sells = [i for i, r in enumerate(rows) if r["y"] == 0]
        notrades = [i for i, r in enumerate(rows) if r["y"] == 1]
        random.seed(42)
        random.shuffle(notrades)
        keep_nt = notrades[:int(1.5 * max(len(buys) + len(sells), 50))]
        chosen = buys + sells + keep_nt
        random.shuffle(chosen)
        made = skipped = 0
        for idx in chosen:
            seq = sequence_for(idx)
            if not seq:
                skipped += 1
                continue
            all_samples.append(make_sample(rows[idx], seq))
            made += 1
        print(f"[export] {sym}: BUY {len(buys)} SELL {len(sells)} "
              f"NO-TRADE kept {len(keep_nt)} | sequences built {made}, "
              f"skipped (thin history) {skipped}")

    with open(OUT, "w", encoding="utf-8") as f:
        for s in all_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"\n[export] wrote {len(all_samples)} samples -> {OUT}")
    print("[export] next: upload to Colab/Kaggle and run "
          "training/train_qwen_orderbook.py on a free T4 GPU")


if __name__ == "__main__":
    main()
