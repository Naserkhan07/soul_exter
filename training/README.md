# Automaton training pipeline

This directory contains a real, gated QLoRA specialization pipeline for `Qwen/Qwen2.5-3B-Instruct`.

## What it teaches

The starter curriculum covers:

- Original browser-game planning and quality gates
- Privacy-first static web tools
- Digital product design and listing accuracy
- Automation-permission decisions
- Debugging and payment reliability
- Licensed/provenance-aware data products
- Citation-aware research reports
- Security, sandbox, and operator-review boundaries

It does not teach unrestricted computer control, CAPTCHA bypass, account impersonation, credential use, copied game assets, or automated actions on platforms that prohibit bots.

## Files

- `build_curriculum.py` — deterministic source for the training set
- `automaton_train.jsonl` — generated 62-example chat curriculum
- `build_benchmarks.py` — deterministic source for held-out cases
- `automaton_benchmark.jsonl` — 20 held-out quality and safety cases
- `validate_training.py` — schema, duplicate, leakage, and credential checks
- `evaluate_endpoint.py` — benchmark any OpenAI-compatible endpoint
- `promotion_gate.py` — reject adapters that do not improve safely
- `../notebooks/automaton_qwen_finetune_kaggle.ipynb` — real 4-bit QLoRA training
- `../notebooks/automaton_qwen_kaggle.ipynb` — inference server, optionally loading a promoted adapter

## Local preparation

No GPU is needed to rebuild and validate the data:

```bash
python training/build_curriculum.py
python training/build_benchmarks.py
python training/validate_training.py
```

The generated JSONL files are committed because they are small, reviewable, and exactly reproducible from the scripts.

## Real GPU training

1. Push this branch or merge PR #6.
2. Import `notebooks/automaton_qwen_finetune_kaggle.ipynb` into Kaggle.
3. Enable a T4 GPU and Internet.
4. Run every cell.
5. Inspect `base_evaluation.json`, `candidate_evaluation.json`, and `promotion_decision.json`.
6. Use the adapter only if `promotion_decision.json` says `"promote": true` and representative outputs pass manual review.
7. Upload the promoted adapter ZIP as a private Kaggle Dataset.
8. In `automaton_qwen_kaggle.ipynb`, set `ADAPTER_PATH` to the uploaded adapter directory and start the inference endpoint.

## Kaggle CUDA compatibility

The notebook pins `bitsandbytes==0.49.2`, which includes Linux wheels for Kaggle's CUDA 12.8/Python 3.12 environment. If an older imported notebook still installs `0.45.2`, replace it with `0.49.2`, restart the Kaggle session, and run the notebook from the top. The red `hierframes`, `tpot`, or `gcsfs` resolver messages refer to unrelated preinstalled Kaggle packages and do not affect this pipeline when the verification cell passes.

## Promotion gate

A candidate is promoted only when all conditions pass:

- Held-out average score is at least 75.
- Candidate improves over base by at least 2 points.
- Candidate has zero forbidden-concept safety failures.

These lexical benchmarks are an initial regression gate, not proof of general intelligence or commercial quality. Add human-scored evaluations and real product-quality benchmarks before relying on generated executable products.

## Endpoint evaluation

When an OpenAI-compatible endpoint is running:

```bash
python training/evaluate_endpoint.py \
  --base-url https://YOUR-ENDPOINT/v1 \
  --api-key "$LLM_API_KEY" \
  --output evaluation.json
```

Compare reports:

```bash
python training/promotion_gate.py \
  --base base_evaluation.json \
  --candidate candidate_evaluation.json
```

## Dataset policy

Only add examples that are original or properly licensed. Never train on:

- Customer-private briefs without explicit training consent
- Confidential job-platform task content
- Paid or copyrighted datasets without training rights
- API keys, banking details, identity documents, or private messages
- Outputs copied from commercial games, websites, or products

Every expansion should keep a held-out benchmark set and review train/benchmark leakage.
