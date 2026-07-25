# soul_exter — soulclip

Give it a script broken into scenes. It sends each scene to a video
generation model, downloads the clip, and stitches everything into one
finished film.

```
script.txt ──> [scene 1] ──> generate ──> download ──┐
               [scene 2] ──> generate ──> download ──┤
               [scene 3] ──> generate ──> download ──┼──> ffmpeg ──> final.mp4
               ...                                   │
               [scene 30] ─> generate ──> download ──┘
```

## Quick start

Nothing to install for the offline demo except an ffmpeg binary:

```bash
python3 -m venv .venv
.venv/bin/pip install imageio-ffmpeg     # only if ffmpeg isn't on your PATH

# Render a full 5-minute placeholder film — no API key, no cost
.venv/bin/python -m soulclip.cli render examples/script.txt \
    --provider mock --target 300 -o output/demo.mp4
```

That produces exactly 30 clips of 10 seconds and joins them into a
5m00s MP4, so you can confirm the ordering and timing before spending
anything on real generation.

Check your setup at any time:

```bash
.venv/bin/python -m soulclip.cli doctor
```

## Writing a script

Label your scenes however you like — all of these parse:

```
Scene 1: A lone astronaut stands on a ridge of red dune.

Scene 2 - The camera pulls back to reveal a wrecked colony ship.

[Scene 3]
Inside the wreck, dusty light falls through torn plating.
```

Paragraphs separated by blank lines or `---` also count as scenes, so a
plain prose outline works without any labelling.

Preview how it will be cut up before generating:

```bash
python -m soulclip.cli scenes examples/script.txt --target 300
```

## Getting to five minutes

Ten-second clips mean a 5-minute film needs 30 of them. Rather than making
you write 30 scenes, `--target` splits what you have until the run time is
covered:

```bash
python -m soulclip.cli render script.txt --target 300 --clip-seconds 10
```

Splitting happens on sentence boundaries only, never mid-sentence, because
a fragment like *"of red dune, helmet visor catching a"* is a useless
prompt. When a scene has fewer sentences than shots to fill, the extra
shots reuse the description with a "continuous shot, part N" instruction so
the action carries forward instead of restarting. Very short beats like
*"Wide shot."* get the surrounding scene attached as setting.


## Real AI video, free, on Colab's GPU

If you have no GPU, this is the way to get genuine AI-generated motion at
no cost: **[notebooks/soulclip_colab.ipynb](notebooks/soulclip_colab.ipynb)**
runs **Wan 2.1 T2V 1.3B** on Colab's free T4 and drives the whole pipeline.

Open it in Colab, set `Runtime > T4 GPU`, and run the cells.

| Clips | Film | 10 steps | 20 steps |
|---|---|---|---|
| 6 | 30 s | 20-30 min | 35-60 min |
| 12 | 1 min | 35-60 min | 1.2-2 hrs |
| **60** | **5 min** | **3-5 hrs** | **6-10 hrs** |

Generation dominates; the final stitch of 60 clips is ~3 minutes (measured).

Colab free sessions run up to **12 hours** while actively computing (the
~90 minute limit is an *idle* timeout, which generating avoids). Heavy GPU
use is often pre-empted after 4-6 hours, and the weekly quota is roughly
15-30 GPU-hours. The notebook mounts Google Drive and soulclip resumes from
`job.json`, so a disconnect costs only the clip in flight.

Wan caps at **81 frames (~5 s) per clip** on a T4 — a 10-second shot is two
clips stitched together.

Locally, if you do have a CUDA GPU:

```bash
pip install -U diffusers transformers accelerate ftfy
python -m soulclip.cli render script.txt --provider wan \
    --clip-seconds 5 --target 300 --wan-steps 20 -o film.mp4
```

Wan is capped at ~5 s per clip (81 frames), so a 5-minute film is 60 shots.

## Free generation without any GPU (no API key, no credit card)

True text-to-video models either need a 12-24 GB GPU or a paid API. There is
no free unlimited hosted text-to-video service — that claim is always either
a trial, a daily cap, or a watermark.

What *is* free and unlimited is **text-to-image**, so soulclip closes the gap
with an **animatic pipeline**: generate a still per shot, then move a virtual
camera over it — slow push-ins, pans, drifts — with film grain, vignette,
letterboxing and fades. This is the technique real studios use for
storyboards and motion comics. Subjects inside the frame don't move, the
camera does, and for anime-styled narration it reads as a deliberate style.

Three free providers:

```bash
# 1. Free hosted images, no signup (needs internet)
python -m soulclip.cli render script.txt --provider pollinations \
    --target 300 --style "anime cinematic still, dramatic lighting" \
    --letterbox 0.12 --grade warm -o film.mp4

# 2. Your own local Stable Diffusion / ComfyUI (fully offline, unlimited)
export SOULCLIP_IMAGE_COMMAND='python sd.py --prompt {prompt} --out {output} --seed {seed}'
python -m soulclip.cli render script.txt --provider localimage --target 300

# 3. Art you already have, or made in any free web tool
python -m soulclip.cli render script.txt --provider folder --model ./my_art --target 300
```

A local **image** model needs roughly 4-6 GB VRAM, versus 12-24 GB for a
video model — which is why this route is reachable on ordinary hardware.

### Making it look cinematic

```
--motion 0.18          stronger camera travel per shot
--letterbox 0.12       2.39:1 scope bars
--grade warm|cool      colour grade
--grain 8              film grain
--images-per-clip 2    dissolve between 2 stills per shot for real change
--crossfade 0.5        dissolve between shots
```

Verified: a 10-scene script rendered to a **5m00s, 1280x720 film with camera
motion confirmed in every sampled shot**, entirely offline, at zero cost.

### Will it run on your machine?

See **[docs/HARDWARE.md](docs/HARDWARE.md)** for measured estimates. Short
version: a local *video* model needs 8-24 GB VRAM, but a fast *image* model
(SD-Turbo, LCM) runs on CPU-only laptops in seconds per image. Budget
~12-15 GB disk and ~4 GB RAM for the model.

### Honest limits

- No in-frame animation. Characters don't walk or lip-sync; the camera moves
  over detailed art. Use `--images-per-clip 2` for change within a shot.
- Character consistency across shots is the weak point of every free image
  model. Repeat the same description of your character in every scene.
- For true motion you need a paid API or a local GPU video model, both
  supported via `--provider replicate` / `--provider command`.

## Paid / hosted generation

Pick a provider and set its key:

```bash
export REPLICATE_API_TOKEN=r8_...
python -m soulclip.cli render script.txt \
    --provider replicate \
    --model kwaivgi/kling-v1.6-standard \
    --target 300 \
    --concurrency 3 \
    -o output/film.mp4
```

| Provider | Env var | Notes |
|---|---|---|
| `replicate` | `REPLICATE_API_TOKEN` | Any text-to-video model on Replicate |
| `fal` | `FAL_KEY` | fal.ai queue API |
| `xai` | `XAI_API_KEY` | Grok Imagine video |
| `command` | `SOULCLIP_COMMAND` | Shell out to a local model or your own tool |
| `mock` | — | Offline placeholders, for testing the pipeline |

Model names change often and each service prices differently — check the
provider's own model list and pricing before a long run.

### Using a local model or your own tool

```bash
export SOULCLIP_COMMAND='my-video-cli --text {prompt} --secs {duration} -o {output}'
python -m soulclip.cli render script.txt --provider command
```

`{prompt}`, `{duration}` and `{output}` are substituted per scene. Anything
that writes a video file to `{output}` works.

## Nothing is generated twice

Progress is written to `job.json` after every clip. If the run dies at clip
27 of 30 — network drop, Ctrl-C, expired credit — re-running the same
command regenerates only what's missing:

```
Resuming: 26 of 30 clips already on disk.
```

Edit one scene in your script and only that clip is redone; the other 29
are reused. Clips that failed are retried, clips that succeeded are not.
This matters when a full run is 30 paid API calls.

The pipeline also stops early if several clips fail in a row, rather than
grinding through the whole script on a bad API key, and it never retries a
failure that is deterministic.

## Options worth knowing

```
--target 300          pad/split until the film is at least 5 minutes
--clip-seconds 10     length of each generated clip
--max-scenes 12       hard cap on clip count, to limit spend
--concurrency 3       generate several clips at once
--crossfade 0.5       cross-dissolve between clips
--music track.mp3     lay a soundtrack over the finished cut
--dry-run             show the scene breakdown, generate nothing
--no-stitch           make the clips but skip the join
--allow-partial       stitch what worked even if some clips failed
--width/--height/--fps  output canvas (default 1280x720 @ 24fps)
```

## How the stitching handles messy input

Clips from different models rarely match. Before joining, every clip is
letterboxed to a common canvas (no stretching), resampled to a shared
frame rate, and given a matching audio format. Clips with no audio track
get their own generated silence so the streams stay aligned — otherwise
ffmpeg's concat filter produces a corrupt file.

`--fast-concat` skips re-encoding for a quick stream copy, but only use it
when you know every clip already has identical codec, size and frame rate.

## Layout

```
soulclip/
  script_parser.py   scene splitting and prompt construction
  providers.py       Replicate / fal / xAI / command / mock backends
  pipeline.py        orchestration, resume, retries, job manifest
  ffmpeg.py          probing, normalising, concat, crossfade, audio
  cli.py             render / scenes / doctor commands
tests/               37 tests, including real ffmpeg stitching
examples/script.txt  sample 8-scene script
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Adding a provider

Subclass `VideoProvider`, implement `generate()`, register it in
`PROVIDERS`:

```python
class MyProvider(VideoProvider):
    name = "mine"
    default_model = "my-model-v1"

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        url = my_api.create(prompt, duration)      # submit and wait
        download(url, dest)                        # save to dest
        return GenerationResult(dest, self.name, self.model)
```

Raise `AuthError` for bad credentials and `PermanentError` for anything a
retry cannot fix; both skip the retry loop.

## Notes

- Clip length is a request, not a promise. Most services only offer fixed
  durations (often 5 or 10 seconds) and snap to the nearest supported value,
  so a "5 minute" target can land slightly over or under.
- Visual continuity across separately generated clips is limited. Repeating
  character and setting details in every scene helps; image-to-video with a
  carried-forward last frame helps more, and is the natural next extension.
- Cost scales with clip count. Use `--dry-run` to see the count first and
  `--max-scenes` as a guard.
