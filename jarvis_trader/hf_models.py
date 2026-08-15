"""
Hugging Face model integration - free, local, no API limits.

Two upgrades cherry-picked from HF (the rest of the "trading" search results
are hobby uploads; these are the industrial-grade ones):

1. FinBERT  (ProsusAI/finbert, ~110M params)
   Finance-tuned news sentiment. Replaces the keyword scorer so the NEWS
   council vote understands sentences, not just words. Runs on CPU in ~50ms.

2. Chronos-Bolt (amazon/chronos-bolt-small, ~48M params)
   Amazon's time-series foundation model. Fed our candle closes it returns a
   probabilistic forecast of the next N bars -> becomes the FORECASTER
   council member. CPU-friendly.

Both are OPTIONAL: if `transformers`/`chronos-forecasting` aren't installed
(or downloads fail), everything degrades gracefully to the existing engines.

Install on your PC:
    pip install -r requirements-ai.txt
First run downloads the weights (~600MB total) into the HF cache, then
everything is offline/local forever.
"""
import os
import socket
import threading

_lock = threading.Lock()


def _hub_reachable(timeout=3):
    """Quick check: can we reach the HF hub (or is a local cache present)?
    Avoids minutes of internal retry loops when offline."""
    # cached weights work fully offline
    cache = os.path.expanduser(os.getenv("HF_HOME", "~/.cache/huggingface"))
    if os.path.isdir(os.path.join(cache, "hub")):
        for d in os.listdir(os.path.join(cache, "hub")):
            if "finbert" in d.lower() or "chronos" in d.lower():
                return True
    try:
        # full HTTPS probe (a plain TCP connect can pass through firewalls
        # that then kill the TLS handshake)
        import requests
        requests.head("https://huggingface.co", timeout=timeout)
        return True
    except Exception:
        return False
_finbert = None            # (tokenizer, model) or False if unavailable
_chronos = None            # pipeline or False if unavailable

STATUS = {"finbert": "not loaded", "chronos": "not loaded"}


# ------------------------------------------------------------------ #
#  FinBERT - financial news sentiment
# ------------------------------------------------------------------ #
def _load_finbert():
    global _finbert
    with _lock:
        if _finbert is not None:
            return _finbert
        try:
            if not _hub_reachable():
                raise RuntimeError("HF hub unreachable and no cached weights")
            from transformers import (AutoTokenizer,
                                      AutoModelForSequenceClassification)
            import torch  # noqa: F401
            tok = AutoTokenizer.from_pretrained("ProsusAI/finbert")
            mdl = AutoModelForSequenceClassification.from_pretrained(
                "ProsusAI/finbert")
            mdl.eval()
            _finbert = (tok, mdl)
            STATUS["finbert"] = "ok (ProsusAI/finbert)"
        except Exception as e:
            _finbert = False
            STATUS["finbert"] = f"unavailable ({str(e)[:60]})"
        return _finbert


def finbert_available():
    return bool(_load_finbert())


def finbert_sentiment(texts):
    """
    Score a list of headlines with FinBERT.
    Returns list of floats in [-1, +1]  (positive - negative probability),
    or None if FinBERT is unavailable.
    """
    fb = _load_finbert()
    if not fb:
        return None
    tok, mdl = fb
    try:
        import torch
        with torch.no_grad():
            enc = tok(list(texts), return_tensors="pt", padding=True,
                      truncation=True, max_length=64)
            probs = torch.softmax(mdl(**enc).logits, dim=-1)
        # ProsusAI/finbert label order: positive, negative, neutral
        out = (probs[:, 0] - probs[:, 1]).tolist()
        return [max(-1.0, min(1.0, s)) for s in out]
    except Exception as e:
        STATUS["finbert"] = f"error ({str(e)[:60]})"
        return None


# ------------------------------------------------------------------ #
#  Chronos - time-series foundation model forecaster
# ------------------------------------------------------------------ #
def _load_chronos():
    global _chronos
    with _lock:
        if _chronos is not None:
            return _chronos
        try:
            if not _hub_reachable():
                raise RuntimeError("HF hub unreachable and no cached weights")
            from chronos import BaseChronosPipeline
            import torch
            _chronos = BaseChronosPipeline.from_pretrained(
                "amazon/chronos-bolt-small",
                device_map="cpu", torch_dtype=torch.float32)
            STATUS["chronos"] = "ok (amazon/chronos-bolt-small)"
        except Exception as e:
            _chronos = False
            STATUS["chronos"] = f"unavailable ({str(e)[:60]})"
        return _chronos


def chronos_available():
    return bool(_load_chronos())


def chronos_forecast(closes, horizon=12):
    """
    Probabilistic forecast of the next `horizon` closes.

    Returns dict:
      score      -100..+100 directional vote (expected move vs recent vol)
      prob_up    fraction of forecast mass above the last close
      exp_move   expected % move of the median path at the horizon
    or None if Chronos is unavailable.
    """
    cp = _load_chronos()
    if not cp:
        return None
    try:
        import torch
        ctx = torch.tensor(list(closes)[-160:], dtype=torch.float32)
        # quantile forecast: [q10, q20, ..., q90]
        quantiles, _ = cp.predict_quantiles(
            context=ctx, prediction_length=int(horizon),
            quantile_levels=[0.1, 0.25, 0.5, 0.75, 0.9])
        q = quantiles[0]                     # [horizon, 5]
        last = float(ctx[-1])
        med_end = float(q[-1, 2])            # median path at horizon
        exp_move = (med_end - last) / last if last else 0.0
        # prob_up: how many quantile-ends sit above the last close
        ends = [float(q[-1, i]) for i in range(q.shape[1])]
        prob_up = sum(1 for e in ends if e > last) / len(ends)
        # scale expected move by recent volatility so the vote is comparable
        # across assets: 1x the 20-bar sigma of returns -> ~60 points
        import statistics
        rets = [(closes[i] / closes[i - 1] - 1) for i in
                range(max(1, len(closes) - 20), len(closes))]
        sigma = (statistics.pstdev(rets) or 1e-6) * (horizon ** 0.5)
        score = max(-100.0, min(100.0, (exp_move / sigma) * 60))
        # blend with prob_up for stability
        score = 0.7 * score + 0.3 * ((prob_up - 0.5) * 200)
        return {"score": round(max(-100, min(100, score)), 1),
                "prob_up": round(prob_up, 3),
                "exp_move": round(exp_move * 100, 4)}
    except Exception as e:
        STATUS["chronos"] = f"error ({str(e)[:60]})"
        return None


def status():
    return dict(STATUS)


def warmup_async():
    """Load both models in a background thread at engine start."""
    def _w():
        _load_finbert()
        _load_chronos()
    threading.Thread(target=_w, daemon=True).start()
