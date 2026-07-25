# What this costs in rupees

Rate used: **1 USD = ₹96.5** (24 July 2026). Rates move — re-check before
committing to anything.

A "5-minute film" throughout means **60 clips of ~5 seconds** = 300 seconds
of generated video.

## Free — ₹0

| Option | Allowance | Time for a 5-min film |
|---|---|---|
| **Kaggle** | 30 GPU-h/week, 2× T4 | ~25–35 min (both GPUs) |
| **Google Colab** | 15–30 GPU-h/week, 1× T4 | ~45–60 min |
| **Your laptop** (still-motion) | unlimited, no GPU | ~15–25 min |

No credit card for any of these. The only real cost is electricity — a
laptop drawing ~45 W for an hour is well under ₹1.

**Kaggle's 30 h/week ≈ 29–40 five-minute films per week, at ₹0.**

## Renting a GPU

A 5-minute film is 1–2 GPU-hours.

| Provider | Per hour | **Per film** |
|---|---|---|
| Vast.ai | ₹7–19 | **₹7–39** |
| RunPod | ₹16–43 | **₹16–85** |
| Lightning AI (T4) | ₹28 | ₹28–56 |
| Thunder Compute | ₹34 | ₹34–68 |
| Paperspace | ₹43–49 | ₹43–98 |

A rented RTX 4090 finishes a film in ~20 minutes for **under ₹20** — less
than a cup of chai, and no quota or session limits.

## Paid video APIs — the expensive route

These charge per second of output, so a 5-minute film is 300 billable
seconds.

| Service | Per second | **5-minute film** |
|---|---|---|
| Fal.ai (Wan 2.6) | ₹2.8–4.8 | **₹840–1,450** |
| Replicate (cheapest route) | ₹6.8 | **₹2,030** |
| Runway Gen-4.5 | ₹24 | **₹7,240** |
| Replicate (Kling) | ₹27 | **₹8,110** |

## Subscriptions

| | Per month |
|---|---|
| Colab Pro | ₹964 |
| Colab Pro+ | ₹4,824 |

Not worth it for this workload — Kaggle's free tier gives more GPU hours
than Colab Pro's compute units typically buy.

## Summary

| Route | Cost per 5-min film |
|---|---|
| **Kaggle / Colab free** | **₹0** |
| Rented GPU | ₹7–85 |
| Fal.ai API | ₹840–1,450 |
| Replicate / Runway | ₹2,000–8,100 |

The free path costs nothing and is what this project is built around. If
you outgrow it, rent a GPU — at ₹7–85 per film it is roughly **100× cheaper
than the hosted APIs** for the same output.
