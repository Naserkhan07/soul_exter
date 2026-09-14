"""Train the six desks — for real, on this box, with no API keys.

    python -m soul.train --dataset-only            # build the JSONL, train nothing
    python -m soul.train --desks all --epochs 2    # LoRA per desk
    python -m soul.train --desks QUANT,RISK --base-model Qwen/Qwen2.5-3B-Instruct

What it does, in order:

1. Builds the supervised dataset from the session (curriculum + the rules the
   debate room agreed + every settled council decision, see ``training.py``).
2. For each desk, loads that desk's open-weight model in 4-bit, wraps it in a
   LoRA and trains it on the desk's rows — the desk keeps its own weights, so
   QUANT and RISK genuinely stop being the same opinion in different hats.
3. Writes ``<out>/<DESK>/`` (PEFT adapter) and ``<out>/manifest.json``. The
   server loads those automatically when ``SOUL_ADAPTERS`` points at ``<out>``.

On a Kaggle 2xT4 this is the cell that turns a fresh copy of the repo into six
desks that have done their homework. On a CPU-only box there is no training
stack, so it writes the dataset, says exactly what is missing, and exits 0 —
the floor still runs (mock personas) so the rest of the pipeline stays testable.

Deliberately *not* here: any hosted trainer, any API key, any upload of the
trading data. The dataset never leaves the machine.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .brains import PROFILES, PROFILE_STANDARD
from .config import load_config
from .training import DESKS, TrainingBook

log = logging.getLogger("soul.train")


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:                    # pragma: no cover
                continue
    return rows


def _missing_stack() -> Optional[str]:
    """What is absent, in the order a person would install it."""
    for module, why in (
        ("torch", "PyTorch (GPU build)"),
        ("transformers", "transformers"),
        ("peft", "peft (LoRA)"),
        ("datasets", "datasets"),
    ):
        try:
            __import__(module)
        except Exception:
            return f"{why} is not installed"
    return None


def _train_one(key: str, model_id: str, rows: List[Dict[str, Any]], out_dir: Path,
               epochs: int, lr: float, max_len: int, batch: int,
               load_4bit: bool = True) -> Dict[str, Any]:
    """LoRA-tune one desk on its own rows. Returns the manifest entry."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, DataCollatorForLanguageModeling,
                              Trainer, TrainingArguments)

    log.info("[%s] loading %s", key, model_id)
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    kwargs: Dict[str, Any] = {"trust_remote_code": True}
    if load_4bit and torch.cuda.is_available():
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        )
        kwargs["device_map"] = "auto"
    elif torch.cuda.is_available():
        kwargs["torch_dtype"] = torch.bfloat16
        kwargs["device_map"] = "auto"

    model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
    if load_4bit and torch.cuda.is_available():
        model = prepare_model_for_kbit_training(model)

    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def encode(row: Dict[str, Any]) -> Dict[str, Any]:
        """One row, as the chat template the desk was actually prompted with."""
        text = tok.apply_chat_template(row["messages"], tokenize=False, add_generation_prompt=False)
        enc = tok(text, truncation=True, max_length=max_len)
        enc["labels"] = list(enc["input_ids"])
        return enc

    data = Dataset.from_list([encode(r) for r in rows])
    args = TrainingArguments(
        output_dir=str(out_dir / key / "checkpoints"),
        num_train_epochs=epochs, learning_rate=lr,
        per_device_train_batch_size=batch, gradient_accumulation_steps=4,
        logging_steps=5, save_strategy="no", report_to=[],
        bf16=torch.cuda.is_available(), fp16=False, optim="adamw_torch",
    )
    trainer = Trainer(
        model=model, args=args, train_dataset=data,
        data_collator=DataCollatorForLanguageModeling(tok, mlm=False),
    )
    t0 = time.time()
    result = trainer.train()
    out_dir.joinpath(key).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir / key))
    tok.save_pretrained(str(out_dir / key))
    entry = {
        "desk": key, "model": model_id, "rows": len(rows), "epochs": epochs,
        "loss": float(getattr(result, "training_loss", 0.0) or 0.0),
        "seconds": round(time.time() - t0, 1), "adapter": str(out_dir / key),
    }
    log.info("[%s] trained on %d rows in %.0fs (loss %.4f)", key, len(rows),
             time.time() - t0, entry["loss"])
    return entry


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Train the SOUL EXTER desks on their own trading record.")
    ap.add_argument("--dataset", default=None, help="JSONL to read/write (default: cfg.training_dataset)")
    ap.add_argument("--dataset-only", action="store_true", help="build the dataset and stop")
    ap.add_argument("--desks", default="all", help="all | CSV of QUANT,RISK,NEWS,MACRO,COMPLIANCE,CEO")
    ap.add_argument("--out", default=None, help="adapter output directory")
    ap.add_argument("--dataset-from", default=None, help="train on an existing JSONL instead of building one")
    ap.add_argument("--profile", default=None, help="model profile: low | standard | variety")
    ap.add_argument("--base-model", default=None, help="override the model for every desk (smoke test)")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--full-precision", action="store_true", help="do not quantise to 4-bit")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
                        datefmt="%H:%M:%S")

    cfg = load_config()
    profile = args.profile or cfg.model_profile
    roster = PROFILES.get(profile, PROFILE_STANDARD)
    book = TrainingBook(cfg)
    if args.out:
        book.adapters_dir = Path(args.out)
        book.adapters_dir.mkdir(parents=True, exist_ok=True)
    dataset = Path(args.dataset) if args.dataset else book.dataset_path

    # 1. the dataset ---------------------------------------------------------
    if args.dataset_from:
        rows = _load_rows(Path(args.dataset_from))
        manifest = {"path": args.dataset_from, "rows": len(rows), "source": "existing"}
    else:
        manifest = book.build(dataset)
        rows = _load_rows(dataset)
    print(json.dumps({"dataset": manifest}, indent=2))
    if args.dataset_only:
        return 0

    # 2. the training stack --------------------------------------------------
    missing = _missing_stack()
    selected = [d.upper() for d in (DESKS if args.desks == "all" else args.desks.split(",")) if d.strip()]
    status = {
        "started_at": time.time(), "profile": profile,
        # what was actually trained on: the session export when one was given,
        # the freshly built file otherwise
        "dataset": str(args.dataset_from or dataset),
        "rows": len(rows), "desks": selected, "trained": {}, "skipped": {},
        "device": "cpu",
    }
    if missing:
        msg = (f"{missing}. The dataset above is ready and the floor runs without it "
               f"(mock personas on CPU). To train the real weights, run this on a GPU box "
               f"(Kaggle 2xT4): pip install -q transformers peft datasets accelerate "
               f"bitsandbytes && python -m soul.train --desks all --epochs 2")
        print(f"\n[training] {msg}\n")
        status.update({"status": "not-trained", "reason": missing})
    else:                                                   # pragma: no cover - GPU only
        import torch
        status["device"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
        by_desk: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            by_desk.setdefault(row["meta"]["desk"], []).append(row)
        for key in selected:
            desk_rows = by_desk.get(key) or []
            if not desk_rows:
                status["skipped"][key] = "no rows"
                continue
            model_id = args.base_model or roster.get(key) or PROFILE_STANDARD.get(key)
            try:
                status["trained"][key] = _train_one(
                    key, model_id, desk_rows, book.adapters_dir, args.epochs, args.lr,
                    args.max_len, args.batch, load_4bit=not args.full_precision)
            except Exception as exc:                        # pragma: no cover
                log.exception("training %s failed: %s", key, exc)
                status["skipped"][key] = f"failed: {exc}"
        status["status"] = "trained" if status["trained"] else "not-trained"
        status["finished_at"] = time.time()

    # 3. the manifest the server reads back ----------------------------------
    manifest_path = book.adapters_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
    print(json.dumps(status, indent=2, default=str))
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(main())
