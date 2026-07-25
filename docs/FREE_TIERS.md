# Is there anything free *and* unlimited?

**No.** Every free GPU tier is a quota, not an unlimited tap. But the quotas
are large enough to be genuinely useful, and Kaggle is the best of them.

Checked July 2026. I could not reach these hosts from my sandbox, so this is
from published documentation rather than my own testing — verify the numbers
before planning around them.

## The free tiers

| Platform | Free allowance | GPU | Session | Signup |
|---|---|---|---|---|
| **Kaggle** | **30 h/week guaranteed** | **2x T4 (32 GB)** or P100 | 9-12 h | no card, phone verify |
| Google Colab | 15-30 h/week, varies | 1x T4 (15 GB) | 12 h | no card |
| Lightning AI | ~80 h/month | T4 / A10G | ~3 h | phone verify |
| SageMaker Studio Lab | 4 h per 24 h | T4 | 4 h | AWS account, no card |
| Paperspace Gradient | no weekly cap* | M4000 (8 GB) | 6 h | *queues at peak |
| Modal | $5-30/month credit | your choice | n/a | credit, not hours |

## Why Kaggle wins for this

| | Kaggle | Colab free |
|---|---|---|
| Weekly GPU | 30 h **guaranteed** | 15-30 h, demand-dependent |
| GPUs | **2x T4** | 1x T4 |
| Background execution | **yes** | no (Pro+ only) |
| Download speed | ~1-2 GB/s | ~500 Mb/s |
| Quota visibility | clear counter | none |

The two GPUs matter here: `notebooks/soulclip_kaggle.ipynb` runs two workers
in parallel via `--scenes`, roughly halving wall-clock time.

## What the quotas buy

A 5-minute film is 60 LTX clips. At 512x320 on T4-class hardware that is
roughly 45-62 minutes of GPU time (single GPU).

| Platform | Films per week |
|---|---|
| Kaggle (30 h) | ~29-40 |
| Colab (~22 h) | ~21-29 |
| Both | ~50-69 |

Effectively unlimited for personal use — but a hard ceiling, not infinity.

## Warnings

- **Kaggle bans GPU-only accounts.** There are reported bans for using the
  platform purely to harvest GPU hours without taking part in competitions.
  Use it in moderation.
- **Multiple accounts to dodge quotas violates the terms** of both Colab and
  Kaggle. Don't.
- **Free tiers are not guaranteed capacity.** At peak times a free Colab
  session can silently drop to CPU.

## If you outgrow the free tiers

Renting is cheap for this workload. A 5-minute film is 1-2 GPU-hours:

| Provider | Rate | Per film |
|---|---|---|
| Vast.ai | from ~$0.07/h | pennies |
| RunPod | from ~$0.17/h | ~$0.20-0.35 |
| Lightning AI | ~$0.29/h (T4) | ~$0.30-0.60 |

A rented RTX 4090 finishes a 5-minute film in roughly 20 minutes for under
50 cents — cheaper than the time spent working around free-tier limits.
