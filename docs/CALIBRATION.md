# How the floor earns its edge (calibration log)

Every number the product claims is produced by a script in `backend/scripts/`. Run them in
order to reproduce the calibration from scratch on any machine with numpy.

## 1 · Does the tape pay at all?

`python3 scripts/edge_study.py --symbols 26 --cycles 20`
→ 942 probes, expectancy +0.035R: the raw tape is a coin flip. Trend alignment and
maturity (distance from the mean) are the only features that separate anything.

## 2 · Which geometry pays?

`python3 scripts/geometry_study.py --symbols 24 --cycles 26`
→ tight stops (0.85×ATR) lose (−0.12R); wide stops with a far target (1.30–1.60×ATR stop,
2.9–3.4×ATR target) pay, because the tape's moves are fat-tailed and persistent.

## 3 · Which entry rule survives other seeds?

`python3 scripts/grid_study.py --symbols 18 --cycles 22 --seeds 20250914,777,31337,4242,99`
→ the winner is *efficiency-gated trend continuation*: efficiency > 0.32, |trend composite| >
0.30, stop 1.0×ATR, target 2.2×ATR, 600s window → mean +0.49R, **worst seed +0.19R**.
Momentum gates (|trend| > 0.45) were *worse*: late entries into a mature move revert.

## 4 · What tape character makes that earnable?

`python3 scripts/character_study.py --symbols 20 --cycles 30`
→ persistent order flow (momo share 0.14–0.24, φ 0.80–0.90), dealer fade 0.12/minute in
ranges, regime mix 30/30/28/12 (up/down/range/squeeze). Fade-the-extreme rules were
negative everywhere (−0.4 to −0.7R); following an efficient trend was positive on every seed
(+0.14 to +0.29R).

## 5 · Which evidence predicts realised R?

`python3 scripts/train_scorecards.py --symbols 22 --cycles 34`
→ 647 settled tickets, ridge fit with z-clipped terms. Out-of-sample quintiles of the fitted
score: Q1 +0.22R → Q5 +0.77R. The desks load this model
(`soul_exter_scorecard_weights.json`); without it they fall back to their hand-written cards.

## 6 · Do the six desks separate winners from losers?

`python3 scripts/council_study.py --symbols 20 --cycles 26 --seed 4242` (seed not used in
training)
→ each desk approves a cohort worth ≈ +0.4 to +0.9R and rejects one worth ≈ −0.1 to −1.0R.
Council verdicts: accept 66–69% at +0.70R mean, reject at −0.17R mean.

## 7 · What does the whole floor earn?

`python3 tests/track_record.py 300 16`
→ 131 tickets, 28 filled, +13.60R realised (mean +0.486R/ticket, 46% win rate on a 2.2:1
payoff). Rejected tickets' counterfactual is reported alongside so the veto quality is visible
rather than hidden.

## Re-tuning on a different tape

Point `SOUL_EXTER_WEIGHTS` at a freshly trained `soul_exter_scorecard_weights.json`, or re-run
steps 3/5 after changing `market/feed.py`'s character constants (`InstrumentState`). The
playbook keeps adapting live from realised outcomes regardless.
