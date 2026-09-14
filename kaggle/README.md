# Running SOUL EXTER on a free Kaggle GPU

Everything here is free and key-less: Kaggle's T4 hours, Hugging Face's ungated open weights, and a
Cloudflare quick tunnel for viewing. No account, token or API key is needed anywhere.

## Steps

1. **Create the notebook.** kaggle.com → *Create → Notebook*. Then **Settings → Accelerator → GPU
   T4 x2** and **Settings → Internet → On** (internet must be on: it is how the weights download and
   how live Binance prices reach the desk; the simulator covers you if it is off).
2. **Import the notebook.** *File → Import Notebook* and pick `soul_exter_kaggle.ipynb` from this
   repo (or upload the file). It clones this repo into `/kaggle/working/soul_exter`.
3. **Run cells 1 → 5 in order.**
   - cell 1 confirms the two T4s
   - cell 2 installs deps (~3 min the first time)
   - cell 3 clones the branch the work lives on (`SOUL_BRANCH`, default
     `arena/01a09bbe-soul-exter`) and falls back to the default branch if it is not there,
     then points `HF_HOME` at `/kaggle/working/hf`
   - cell 4 loads **one** cabin and prints its verdict — a smoke test before you spend 15 minutes
     downloading the rest
   - cell 5 starts the engine and opens the tunnel, then prints a URL like
     `https://something-random.trycloudflare.com`
4. **Open that URL.** You are on the floor. Weights download in the background the first time a
   trade reaches a cabin, so the first trade is slow and the rest speed up.
5. **Cell 6 keeps the session alive** and prints council/P&L/GPU stats every 30 seconds. Kaggle
   idles notebooks after ~20 minutes of inactivity, so leave it running (or let it die and re-run
   cell 5 — the weights are cached).

## Pace expectations

| profile | cabins | first trade | steady state |
|---|---|---|---|
| `standard` (default) | Qwen-7B, Mistral-7B, Zephyr-7B, Phi-3.5-mini, Qwen-3B, **CEO Qwen-14B** | 3–6 min (downloads) | ~1–3 trades/min, 2 waves + CEO on splits |
| `variety` | Qwen-3B, Mistral-7B, Zephyr-7B, Qwen-7B, Phi-3.5-mini, **CEO Qwen-14B** | 3–6 min | same |
| `low` | 3B + Phi-mini throughout, CEO Qwen-7B | 1–2 min | ~3–6 trades/min |

### Training the desks (cell 5b)

The floor trains itself while it trades. Every closed position labels the verdicts that
produced it, and cell 5b exports that session as a supervised dataset, then LoRA-tunes each
desk on its own rows and restarts the server with `SOUL_ADAPTERS` set — so the desks come back
running what they learned. More settled trades first (let it run 15–30 minutes) makes better
labels. Skip 5b and everything still works; the desks simply argue from the playbook and the
debate room's rules instead of from their own record.

Watch VRAM with cell 6. If you OOM, lower `SOUL_MODEL_CACHE` (how many models stay resident) or
switch to `SOUL_MODEL_PROFILE=low`.

## Gotchas

- **20 GB `/kaggle/working` quota.** The 4-bit weights are ~25 GB in total but Hugging Face caches
  the *original* fp16 shards (`~50 GB`). Keep `SOUL_MODEL_PROFILE=standard` or lower, and if a
  download fails with "no space left", delete `/kaggle/working/hf/hub` and re-run with the `low`
  profile, or attach a Kaggle Dataset containing the weights and point `HF_HOME` at it.
- **The tunnel URL changes every run.** Re-run cell 5 to get a fresh one.
- **Session length.** Kaggle caps GPU sessions (~9–12 h) and refreshes weekly quotas. Nothing here
  writes to disk outside `/kaggle/working`, so a kill is survivable: re-run cells 3 and 5.
- **Internet off?** Everything still runs — the market layer falls back to its correlated simulator
  and the UI badge shows `feed: simulator`.
- **`SOUL_WAVE_MODE=0`** switches to strictly sequential cabins (QUANT → RISK → NEWS → MACRO →
  COMPLIANCE → CEO, each seeing all predecessors). It is 3–4× slower; use it when you would rather
  have the literal flow than the throughput.
