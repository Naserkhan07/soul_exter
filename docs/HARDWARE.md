# Will a local model run on your laptop?

Reference target: **Dell Latitude E7450 — i7-5600U (2 cores / 4 threads,
Broadwell 2015), 16 GB RAM, Intel HD 5500 integrated graphics, Windows 10.**

## Short answer

**Yes — but only image models, and only the fast ones.**

| | Verdict |
|---|---|
| Local **video** model (Wan, CogVideoX, LTX, Mochi) | ❌ Impossible — needs 8–24 GB **VRAM**; you have none |
| Local **image** model, SD 1.5 at 20 steps | ⚠️ Works but painful — ~4–9 min per image |
| Local **image** model, 1–4 step (Turbo/LCM) | ✅ **This is your route** — 15–60 s per image |
| soulclip camera motion + stitching | ✅ Fast — ffmpeg only, no model |

The blocker is that your machine has **no dedicated GPU**. The Intel HD 5500
has no usable CUDA path, so everything runs on 2 CPU cores.

## Why video models are out

Measured on this reference hardware class:

```
i7-5600U theoretical peak : 83 GFLOPS (AVX2+FMA, 2 cores)
  realistic for diffusion : ~25 GFLOPS
```

A modern GPU delivers 20,000–80,000 GFLOPS. Video models are roughly
50–200x the compute of a single image because they denoise many frames
jointly. A 5-second clip that takes 60 s on an RTX 4090 would take
**several days** on your CPU — and would exceed RAM before finishing.

This is a hardware wall, not a tuning problem.

## What actually works: fast image models + camera motion

soulclip's free path generates one still per shot and animates it. So you
only need a model that can produce a still in reasonable time.

Projected on your CPU (~25 GFLOPS effective, SD 1.5 UNet ≈ 340 GFLOPs/step):

| Setup | Steps | Per image | **30 stills (5-min film)** |
|---|---|---|---|
| SD 1.5 + CFG | 20 | ~9 min | ~4.5 hours ❌ |
| SD 1.5, no CFG | 20 | ~4.5 min | ~2.3 hours ❌ |
| **LCM / LCM-LoRA** | 4 | **~55 s** | **~27 min** ✅ |
| **SD-Turbo / SDXS** | 1 | **~14 s** | **~7 min** ✅ |
| SD-Turbo @ 768px | 1 | ~31 s | ~15 min ✅ |

These line up with real-world reports: a comparable dual-core laptop
measured ~155 s for SD 1.5 at 20 steps, and ~31 s with a turbo model.

**With OpenVINO** (Intel's own runtime, and your CPU is Intel) expect a
further **2–3x speedup** — FastSD CPU reports ~0.8 s/image on newer Intel
chips. On Broadwell you should land nearer **5–10 s per image**, putting a
full 5-minute film around **5 minutes of generation**.

## Disk and RAM budget

### Download sizes

| Model | Download | RAM while running |
|---|---|---|
| **SDXS-512-0.9** | ~1.2 GB | ~2–3 GB |
| **SD-Turbo** (fp16) | ~2.2 GB | ~3–4 GB |
| **LCM-Dreamshaper-v7** | ~2.2 GB | ~3–4 GB |
| Anime SD 1.5 (Anything v5) | ~2.1 GB | ~3–4 GB |
| LCM-LoRA (bolt onto any SD 1.5) | ~135 MB | — |
| SDXL base | ~6.9 GB | ~9–12 GB ❌ too slow here |

### Install footprint

```
PyTorch CPU wheel                  ~2.5 GB
FastSD CPU app + dependencies      ~1.0 GB
OpenVINO runtime (optional)        ~0.5 GB
Model weights                      ~1.2-2.2 GB
ffmpeg static build                ~0.08 GB
-------------------------------------------
Recommended free disk              12-15 GB
```

### RAM during a run

```
Windows 10 idle              ~3-4 GB
Image model loaded           ~3-4 GB
ffmpeg animating a clip      ~0.3 GB
-------------------------------------
Peak                         ~7-8 GB of your 16 GB
```

**16 GB is comfortable.** You have ~11 GB free per your report, so nothing
will swap. RAM is not your constraint — CPU speed is.

⚠️ Your page file is only 2.88 GB. That's fine for the models above, but
don't attempt SDXL, which would swap heavily and could hang the machine.

### Output sizes

```
30 stills (768x432 jpg)      ~6 MB
30 animated clips (10s)      ~100 MB
final 5-minute 720p mp4      ~95 MB
```

## Recommended setup

**FastSD CPU** — built specifically for CPU-only machines, bundles
OpenVINO, and ships turbo models.

1. Install FastSD CPU: <https://github.com/rupeshs/fastsdcpu>
2. Choose **SD-Turbo** or **SDXS-512**, enable the **OpenVINO** backend.
3. Generate at **512x288** or **768x432** — soulclip upscales and
   letterboxes anyway, and the camera crop hides softness.
4. Point soulclip at it:

```cmd
set SOULCLIP_IMAGE_COMMAND=python -m fastsdcpu --prompt "{prompt}" --output {output} --seed {seed}
python -m soulclip.cli render script.txt --provider localimage ^
    --target 300 --style "anime cinematic still, detailed background art" ^
    --letterbox 0.12 --grade warm --motion 0.18 -o film.mp4
```

Because soulclip saves progress after every clip, you can stop and resume
freely — useful when a run takes 30+ minutes.

## Realistic expectations

| | Estimate |
|---|---|
| Generation (30 stills, turbo + OpenVINO) | ~5–15 min |
| Camera animation (ffmpeg, 30 clips) | ~5–8 min |
| Final stitch | ~1–2 min |
| **Total for a 5-minute film** | **~15–25 min** |

Run it, make tea, come back to a finished film. That is genuinely
unlimited and genuinely free — you pay only in electricity.

### Two honest caveats

- **Turbo models trade quality for speed.** 1-step output is softer and
  less detailed than 20-step SD. For anime backgrounds it holds up well;
  for detailed character close-ups it will disappoint. LCM at 4 steps is
  the better quality/time compromise if you can accept ~27 min.
- **Still no in-frame animation.** Characters won't move or lip-sync — the
  camera moves over the art. That limit is unchanged by any of this.

## First step before committing to a download

Test the whole pipeline with art you already have — no model, no download:

```cmd
python -m soulclip.cli render examples\lighthouse.txt --provider folder ^
    --model .\my_images --target 300 --letterbox 0.12 -o test.mp4
```

If you like the motion and pacing, then install the model. If you don't,
you've saved a 5 GB download.
