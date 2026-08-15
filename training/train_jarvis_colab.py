# %% [markdown]
# # 🧠 Train JARVIS-TRADING-BRAIN on free Colab T4
#
# Fine-tunes a small chat LLM (Qwen2.5-3B-Instruct by default - trains fast
# on T4 AND runs on your laptop CPU afterwards via Ollama) on:
#   1. jarvis_dataset.jsonl  <- YOUR bot's own trade journal + knowledge base
#      (create it first:  python training/export_dataset.py)
#   2. Public HF trading datasets (same ones the gemma-trading-brain used)
#
# HOW TO RUN (Google Colab, free):
#   1. colab.research.google.com -> New notebook -> Runtime > Change type > T4 GPU
#   2. File > Upload: this file's cells (or paste them), plus jarvis_dataset.jsonl
#   3. Run all. ~1-2h. The LoRA adapter saves to ./jarvis-trading-brain-lora
#      and optionally pushes to your HF account.
#   4. To run the result on YOUR LAPTOP CPU: merge + convert to GGUF (last
#      cell) -> `ollama create jarvis-brain -f Modelfile` -> serves locally.

# %% Install
# !pip -q install transformers trl peft accelerate bitsandbytes datasets

# %% Config
BASE_MODEL = "Qwen/Qwen2.5-3B-Instruct"   # small = trains fast + runs on CPU later
OUTPUT_DIR = "./jarvis-trading-brain-lora"
HUB_MODEL_ID = ""                          # e.g. "yourname/jarvis-trading-brain" ('' = don't push)
MAX_SEQ = 1024
EPOCHS = 2
LR = 2e-4
LORA_R, LORA_ALPHA = 32, 64

# %% Load datasets
import json, os
from datasets import load_dataset, Dataset, concatenate_datasets

parts = []

# 1) YOUR bot's own dataset (journal + knowledge) - upload jarvis_dataset.jsonl
if os.path.exists("jarvis_dataset.jsonl"):
    rows = [json.loads(l) for l in open("jarvis_dataset.jsonl", encoding="utf-8")]
    parts.append(Dataset.from_list(rows))
    print(f"jarvis_dataset.jsonl: {len(rows)} samples (YOUR bot's experience)")
else:
    print("! jarvis_dataset.jsonl not found - upload it (export_dataset.py makes it)")

# 2) Public trading datasets (best-effort; skips any that fail)
def alpaca(ex):
    c = ex.get("instruction", "") or ""
    if ex.get("input"):
        c += "\n\n" + str(ex["input"])
    return {"messages": [{"role": "user", "content": c},
                         {"role": "assistant", "content": ex.get("output", "")}]}

def qa(ex):
    return {"messages": [{"role": "user", "content": ex.get("question", "")},
                         {"role": "assistant", "content": ex.get("answer", "")}]}

for name, split, conv, cap in [
        ("yymYYM/stock_trading_QA", "train", qa, 4000),
        ("mrzlab630/trading-candles", "train", alpaca, 4000),
        ("lumalik/Quant-Trading-Instruct", "train",
         lambda ex: {"messages": [
             {"role": "user", "content": f"{ex.get('context','')}\n\n{ex.get('question','')}"},
             {"role": "assistant", "content": ex.get("answer", "")}]}, 500)]:
    try:
        ds = load_dataset(name, split=split)
        ds = ds.map(conv, remove_columns=ds.column_names)
        if len(ds) > cap:
            ds = ds.shuffle(seed=42).select(range(cap))
        parts.append(ds)
        print(f"{name}: {len(ds)} samples")
    except Exception as e:
        print(f"skip {name}: {e}")

train_ds = concatenate_datasets(parts).shuffle(seed=42)
print(f"TOTAL: {len(train_ds)} samples")

# %% Model (4-bit QLoRA)
import torch
from transformers import (AutoModelForCausalLM, AutoTokenizer,
                          BitsAndBytesConfig)
from peft import LoraConfig, prepare_model_for_kbit_training

tok = AutoTokenizer.from_pretrained(BASE_MODEL)
bnb = BitsAndBytesConfig(load_in_4bit=True,
                         bnb_4bit_compute_dtype=torch.bfloat16,
                         bnb_4bit_quant_type="nf4",
                         bnb_4bit_use_double_quant=True)
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL, quantization_config=bnb, device_map="auto",
    torch_dtype=torch.bfloat16)
model = prepare_model_for_kbit_training(model)

peft_cfg = LoraConfig(r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=0.0,
                      bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                      "gate_proj", "up_proj", "down_proj"])

# %% Train
from trl import SFTConfig, SFTTrainer

args = SFTConfig(output_dir=OUTPUT_DIR, num_train_epochs=EPOCHS,
                 per_device_train_batch_size=1, gradient_accumulation_steps=8,
                 learning_rate=LR, lr_scheduler_type="cosine",
                 warmup_ratio=0.03, bf16=True, gradient_checkpointing=True,
                 logging_steps=20, save_steps=400, save_total_limit=2,
                 max_length=MAX_SEQ, report_to="none",
                 push_to_hub=bool(HUB_MODEL_ID),
                 hub_model_id=HUB_MODEL_ID or None)

trainer = SFTTrainer(model=model, args=args, train_dataset=train_ds,
                     peft_config=peft_cfg, processing_class=tok)
trainer.train()
trainer.save_model()
print("DONE ->", OUTPUT_DIR)

# %% (Optional) Convert for your laptop CPU via Ollama
# !pip -q install llama-cpp-python  # or use llama.cpp's convert scripts:
# 1. merge LoRA:   from peft import AutoPeftModelForCausalLM
#    m = AutoPeftModelForCausalLM.from_pretrained(OUTPUT_DIR); m = m.merge_and_unload()
#    m.save_pretrained("./jarvis-merged"); tok.save_pretrained("./jarvis-merged")
# 2. convert to GGUF with llama.cpp:  python convert_hf_to_gguf.py ./jarvis-merged
# 3. quantize: ./llama-quantize jarvis.gguf jarvis-q4.gguf Q4_K_M
# 4. on your laptop:  ollama create jarvis-brain -f Modelfile   (FROM ./jarvis-q4.gguf)
# 5. then set TRADING_BRAIN_URL=http://localhost:11434 in the bot vault
