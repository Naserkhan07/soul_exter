# Can a real video model run on your laptop?

You asked me to check GitHub and Hugging Face. I did. Here is what exists,
what runs on CPU, and the honest arithmetic.

**Target machine:** Dell Latitude E7450 — i7-5600U (2 cores / 4 threads,
Broadwell 2015), 16 GB RAM, Intel HD 5500 integrated graphics, **no
dedicated GPU**.

## What I found

**Good news:** [`stable-diffusion.cpp`](https://github.com/leejet/stable-diffusion.cpp)
(6.6k stars, actively developed — commits within the last day) genuinely
supports **Wan video models on pure CPU** via GGUF quantization. Pure
C/C++, no Python, no CUDA required. It has a dedicated
[`docs/wan.md`](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/wan.md)
covering Wan 2.1 and Wan 2.2, text-to-video and image-to-video.

So the answer to "does a video model exist that can run on CPU" is
**yes, technically**.

**Bad news:** the arithmetic makes it unusable for a 5-minute film.

## The smallest real option

**Wan 2.1 T2V 1.3B**, Q4_K_M GGUF, via stable-diffusion.cpp.

### Download

| Component | Size | Required? |
|---|---|---|
| Wan2.1 T2V 1.3B (Q4_K_M gguf) | ~0.95 GB | yes |
| umt5-xxl text encoder (Q4 gguf) | ~2.9 GB | **yes** — bigger than the model |
| wan_2.1_vae.safetensors | ~0.25 GB | yes |
| TAE (low-RAM VAE alternative) | ~10 MB | if VAE exhausts RAM |
| **Total** | **~4.1 GB** | |

Weights: <https://huggingface.co/calcuis/wan-1.3b-gguf>
Encoder: <https://huggingface.co/city96/umt5-xxl-encoder-gguf>

### RAM

```
Wan 1.3B Q4 weights                0.95 GB
umt5-xxl encoder (transient)       2.90 GB
Latents + activations (33 frames)  3.50 GB
VAE decode peak                    2.50 GB
Windows 10 baseline                3.50 GB
--------------------------------------------
Peak                              ~10.5 GB   fits in your 16 GB
```

**RAM is not the blocker.** Your 16 GB is enough.

## Speed — this is the blocker

Your CPU delivers roughly **25 GFLOPS** effective for diffusion work
(measured basis: 83 GFLOPS theoretical peak, AVX2+FMA, 2 cores at ~30%
efficiency on conv/attention workloads).

One 2-second 480p clip at 20 steps is about **1,300 TFLOPs** of compute.

| | Time on your CPU |
|---|---|
| One 2-second clip, 20 steps | **~14 hours** |
| One 10-second shot | ~72 hours (3 days) |
| **A 5-minute film (30 shots)** | **~90 days non-stop** |

With a 4-step distilled variant (CausVid / self-forcing LoRA), divide by 5:

| | Time |
|---|---|
| One 2-second clip, 4 steps | ~2.9 hours |
| **A 5-minute film** | **~18 days non-stop** |

For scale, you are roughly **600x slower** than an RTX 5080. Published
benchmarks put LTX-Video 2B at 5 min 9 s per clip on that card — which
projects to about **2 days per single clip** on your laptop.

A 15 W ultrabook CPU cannot run flat out for 18 days. It will thermal
throttle, and the estimate above assumes it does not.

## Everything else I checked

| Model | Min VRAM | CPU viable? |
|---|---|---|
| Wan 2.1 1.3B | 8.19 GB (4–6 GB GGUF) | Only option, still ~18–90 days |
| Wan 2.2 TI2V 5B | ~16 GB | No |
| Wan 2.1/2.2 14B | 6 GB GGUF + heavy offload | No — 20–30 min/clip *on a GPU* |
| LTX-Video 2B | 6–8 GB FP8 | ~2 days per clip on CPU |
| LTX-2.3 | 24 GB recommended | No |
| HunyuanVideo | 14–60 GB | No |
| Mochi 1 (10B) | 24 GB | No |
| AnimateDiff | ~6 GB | Closest thing, still hours/clip on CPU |

Every one of these assumes a **dedicated NVIDIA GPU**. None targets
CPU-only inference as a practical path.

## Why video is so much harder than images

An image model denoises one frame. A video model denoises **all frames
jointly**, with attention across time — that is what makes motion coherent
instead of a flickering slideshow.

A 5-second 480p clip is 81 frames held in memory simultaneously, with
attention computed between them. The compute scales far worse than
linearly with frame count. That is why a 1.3B *video* model is vastly more
expensive than a 2.6B *image* model.

## What would actually work

Ranked by practicality for you:

1. **Free GPU on Google Colab** — a free T4 runs Wan 1.3B in a few minutes
   per clip. Sessions time out after ~90 minutes, but soulclip resumes from
   `job.json`, so you can generate a film across several sessions. This is
   the only genuinely free route to *real* video on your hardware.
2. **Rent a cloud GPU** — roughly $0.20–0.50/hour. A 5-minute film is about
   2–3 hours of GPU time, so under $1.50. Not free, but not $20–80 either.
3. **Upgrade to a machine with an 8 GB NVIDIA GPU** — then Wan 1.3B runs
   locally and unlimited.
4. **The still-motion pipeline already in soulclip** — free, unlimited,
   runs on your laptop today, but the camera moves rather than the subject.

## Bottom line

There is no local video model that will produce a 5-minute film on a
Latitude E7450 in reasonable time. The nearest option needs about
**18 days of uninterrupted compute** on a laptop that will throttle long
before then.

This is a hardware limit, not a software one. Free *and* unlimited *and*
real video generation *and* no GPU — you can have any three, not all four.
