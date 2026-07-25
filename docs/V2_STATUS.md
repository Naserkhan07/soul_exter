# v2 plan — what is built, what is not

Tracking the 22-section development plan honestly. This lists what actually
works today, not what is scaffolded.

## Done

| # | Item | Where |
|---|---|---|
| 1 | Character manager (`characters/<name>/profile.json`, reference images) | `characters.py` |
| 2 | Character detection from prose, drafted into profiles | `storyboard.py`, `characters detect` |
| 3 | Prompt builder (shot, cast, action, lighting, style, negative, seed) | `prompts.py` |
| 5 | Persistent voice field on each profile | `characters.py` (`voice`) |
| 6 | Automatic storyboarding from prose | `storyboard.py` |
| 7 | Sentence-boundary scene splitting | `script_parser.py` |
| 8 | Quality checker (exists, duration, resolution, black frames, audio) | `quality.py` |
| 9 | Failure classification with per-kind back-off | `quality.py` |
| 11 | Audio pipeline (narration, ducking, ambience, loop) | `audio.py` |
| 13 | Provider capability registry | `capabilities.py`, `soulclip providers` |
| 14 | Progress display with measured ETA | `pipeline.py` |
| 16 | Checkpointing after every clip, multi-worker safe | `pipeline.py` |
| 20 | 169 automated tests | `tests/` |
| 22 | All previous commands still work | verified by the suite |

## Not built yet

These are real gaps, not oversights:

| # | Item | Why it is not done |
|---|---|---|
| 4 | Image conditioning / frame chaining | Capability flags and reference-image plumbing exist, but the last-frame → next-clip chain is not wired into the providers. Needs a GPU to test meaningfully. |
| 10 | Subtitle generator | Needs word-level timings from the TTS layer to be worth shipping; Kokoro exposes them but the plumbing is not written. |
| 12 | Continuity checker | Would need perceptual hashing or CLIP embeddings across neighbouring clips. Real work, and unverifiable here without GPU output. |
| 15 | Work queue (pause/resume/cancel, multiple jobs) | The single-job resume path covers most of the need; a queue is a larger design. |
| 17 | Plugin auto-discovery | Providers are still registered in `PROVIDERS`. The capability layer was the prerequisite; discovery is a small follow-up. |
| 18 | Config files | Defaults are still CLI flags. |
| 19 | Structured logging to `logs/` | Output goes to stdout via the reporter callback. |
| 21 | Full doc rewrite | README updated for the new commands; architecture diagrams not redrawn. |

## New commands

```bash
soulclip providers                    # capability matrix
soulclip characters list
soulclip characters add --name Father --age 42 --appearance "..."
soulclip characters detect --from-story story.txt
```

## New render flags

```
--characters DIR      character profiles (default: characters/ if present)
--no-characters       ignore profiles
--seed N              base seed; each shot uses seed+index
--negative "..."      extra negative prompt
--no-enrich           send scene text verbatim
--no-quality-check    skip black-frame detection
```
