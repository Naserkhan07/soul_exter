# Running the bot on Kaggle — step by step

Kaggle lends you a machine with **2x NVIDIA T4 GPUs, free**, 30 hours a
week. Your laptop only needs a browser.

## One-time setup

1. Go to **[kaggle.com](https://www.kaggle.com)** and sign up with a Google
   account. No credit card.
2. Click your avatar (top right) > **Settings** > **Phone Verification**.
   **This is required** — GPUs and internet access stay locked without it.

## Every run

3. Go to **[kaggle.com/code](https://www.kaggle.com/code)** > **New Notebook**.
4. **File > Import Notebook > Upload**, and pick
   `notebooks/soulclip_kaggle.ipynb` from this repo.
5. In the **right sidebar**, set:
   - **Session options > Accelerator > GPU T4 x2**
   - **Internet > On**
6. **Run All** (or run cells top to bottom).

Cell 1 checks the GPUs and stops immediately with a clear message if the
accelerator is not set, so you cannot silently waste a run.

## What each cell does

| Cell | Does |
|---|---|
| 1 | Confirms both GPUs are visible |
| 2 | Installs diffusers, clones this repo |
| 3 | Writes your script, shows the scene breakdown |
| 4 | Settings — `CLIPS`, resolution, style |
| 5 | **Generates**, both GPUs in parallel |
| 6 | Stitches every clip into the final film |
| 7 | Plays it inline |
| 8 | Saves it so it survives the session |

## First run

Leave `CLIPS = 6`. That is ~30 seconds of film and finishes in a few
minutes. Watch for this line:

```
      avg 22s/clip · 4 left · ~1 min to go
```

That average is **your measured speed**. Multiply by 60 for a full
5-minute film, then halve it because both GPUs run at once.

Only after you have seen real output should you set `CLIPS = 60`.

## Gotchas

| Problem | Fix |
|---|---|
| `No GPU!` | Sidebar > Session options > Accelerator > **GPU T4 x2** |
| Clone or pip fails | Sidebar > **Internet > On** |
| Out of memory | Set `WIDTH, HEIGHT = 384, 256` |
| Session ended mid-run | Rerun cell 5 — finished clips are reused |
| Output looks soft | Set `768, 512` (roughly 2x slower) |

## Saving your film

`/kaggle/working` is **wiped when the session ends**. Either:
- Download from the **Output** panel in the right sidebar, or
- Click **Save Version** (top right) to keep it with the notebook.

## Limits

| | |
|---|---|
| Weekly GPU | 30 hours, guaranteed |
| Session length | 9-12 hours |
| Cost | Rs 0 |

Roughly 30-40 five-minute films a week, free.

> **Account warning:** Kaggle has banned accounts that only ever consume
> GPU hours without taking part in the community. Use it in moderation.
