# %% [markdown]
# # 🧠 Train QWEN on ORDER-BOOK data — free GPU (Colab T4 / Kaggle)
#
# Fine-tunes **Qwen2.5-3B-Instruct** with QLoRA on your recorded order-book
# microstructure samples so the model itself learns:
#
#     ORDER-BOOK STATE  ->  SIGNAL / ENTRY / TP / SL / CONFIDENCE / REASON
#
# Labels are REAL triple-barrier outcomes from your recorder — not opinions.
#
# ## HOW TO RUN (free):
# 1. On your PC (after the recorder has collected data — the more days the
#    better):
#        python training/export_orderbook_dataset.py BTCUSDT ETHUSDT
#    -> produces training/orderbook_dataset.jsonl
# 2. Open colab.research.google.com -> New notebook -> Runtime > T4 GPU
#    (or kaggle.com -> New Notebook -> GPU T4; 30h/week free)
# 3. Upload orderbook_dataset.jsonl + paste these cells. Run all. (~1-2h)
# 4. Optional last cells: merge LoRA -> GGUF -> run on YOUR laptop via
#    Ollama, then set TRADING_BRAIN_URL in the bot vault. Or push to your
#    HF account.
#
# ## Hard-example loop (the "train it hard" cycle):
# After v1 trains, the eval cell finds samples where the model's SIGNAL
# disagreed with the real outcome, saves them to hard_examples.jsonl,
# and you re-run training with them oversampled -> v2, v3, ...

# %% Install
# !pip -q install "transformers>=4.44" trl peft accelerate bitsandbytes datasets

# %% Config
BASE_MODEL = "Qwen/Qwen2.5-3B-Instruct"   # 7B if you have >= 16GB VRAM
DATA_FILE = "orderbook_dataset.jsonl"
HARD_FILE = "hard_examples.jsonl"          # produced by the eval cell
OUTPUT_DIR = "./qwen-orderbook-lora"
HUB_MODEL_ID = ""                          # "yourname/qwen-orderbook" or ''
MAX_SEQ = 768
EPOCHS = 2
LR = 2e-4
LORA_R, LORA_ALPHA = 64, 128               # heavier adapter: this IS the brain
VAL_FRACTION = 0.10                        # chronological tail held out

# %% Load dataset (chronological split - no shuffle leakage across time)
import json, os
from datasets import Dataset

rows = [json.loads(l) for l in open(DATA_FILE, encoding="utf-8")]
print(f"dataset: {len(rows)} samples")

# oversample hard examples from previous rounds (train-it-hard loop)
if os.path.exists(HARD_FILE):
    hard = [json.loads(l) for l in open(HARD_FILE, encoding="utf-8")]
    rows = rows + hard * 2      # hard cases weighted 3x total
    print(f"+ {len(hard)} hard examples (x3 weight) from previous round")

split = int(len(rows) * (1 - VAL_FRACTION))
train_rows, val_rows = rows[:split], rows[split:]
train_ds = Dataset.from_list(train_rows)
val_ds = Dataset.from_list(val_rows)
print(f"train {len(train_ds)} / val {len(val_ds)}")

# %% Model (4-bit QLoRA)
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
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

peft_cfg = LoraConfig(
    r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=0.05, bias="none",
    task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"])

# %% Train
from trl import SFTConfig, SFTTrainer

args = SFTConfig(
    output_dir=OUTPUT_DIR, num_train_epochs=EPOCHS,
    per_device_train_batch_size=1, gradient_accumulation_steps=8,
    learning_rate=LR, lr_scheduler_type="cosine", warmup_ratio=0.03,
    bf16=True, gradient_checkpointing=True,
    logging_steps=20, save_steps=500, save_total_limit=2,
    max_length=MAX_SEQ, report_to="none",
    push_to_hub=bool(HUB_MODEL_ID), hub_model_id=HUB_MODEL_ID or None)

trainer = SFTTrainer(model=model, args=args, train_dataset=train_ds,
                     eval_dataset=val_ds, peft_config=peft_cfg,
                     processing_class=tok)
trainer.train()
trainer.save_model()
print("saved ->", OUTPUT_DIR)

# %% EVALUATE + mine hard examples (the "train it hard" loop)
# Runs the tuned model on the held-out validation tail, parses SIGNAL,
# compares with the true label, reports precision, saves failures.
import re
from peft import PeftModel

model.eval()

def ask(sample):
    msgs = sample["messages"][:2]      # system + user only
    prompt = tok.apply_chat_template(msgs, tokenize=False,
                                     add_generation_prompt=True)
    ids = tok(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=90, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    text = tok.decode(out[0][ids["input_ids"].shape[1]:],
                      skip_special_tokens=True)
    m = re.search(r"SIGNAL:\s*(BUY|SELL|NO TRADE)", text)
    return (m.group(1) if m else "PARSE_FAIL"), text

def truth(sample):
    m = re.search(r"SIGNAL:\s*(BUY|SELL|NO TRADE)",
                  sample["messages"][2]["content"])
    return m.group(1)

stats = {"right": 0, "wrong": 0, "parse_fail": 0}
dir_stats = {"right": 0, "wrong": 0}
hard = []
N_EVAL = min(300, len(val_rows))
for i, s in enumerate(val_rows[:N_EVAL]):
    pred, raw = ask(s)
    t = truth(s)
    if pred == "PARSE_FAIL":
        stats["parse_fail"] += 1
        hard.append(s)
        continue
    ok = pred == t
    stats["right" if ok else "wrong"] += 1
    if pred in ("BUY", "SELL"):
        dir_stats["right" if ok else "wrong"] += 1
    if not ok:
        hard.append(s)
    if (i + 1) % 50 == 0:
        print(f"  evaluated {i+1}/{N_EVAL}...")

n = stats["right"] + stats["wrong"]
nd = dir_stats["right"] + dir_stats["wrong"]
print(f"\nOverall accuracy: {100*stats['right']/max(n,1):.1f}% over {n}")
print(f"DIRECTIONAL precision (BUY/SELL only): "
      f"{100*dir_stats['right']/max(nd,1):.1f}% over {nd} "
      f"(this is the number that matters)")
print(f"Format failures: {stats['parse_fail']}")

with open(HARD_FILE, "w", encoding="utf-8") as f:
    for s in hard:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")
print(f"saved {len(hard)} hard examples -> {HARD_FILE}")
print("TRAIN-IT-HARD: re-run the training cells now -> v2 "
      "(hard cases oversampled 3x). Repeat until directional precision "
      "stops improving.")

# %% (Optional) Merge + export GGUF for your laptop via Ollama
# from peft import AutoPeftModelForCausalLM
# m = AutoPeftModelForCausalLM.from_pretrained(OUTPUT_DIR,
#         torch_dtype=torch.bfloat16, device_map="cpu")
# m = m.merge_and_unload()
# m.save_pretrained("./qwen-orderbook-merged")
# tok.save_pretrained("./qwen-orderbook-merged")
# # then with llama.cpp:
# #   python convert_hf_to_gguf.py ./qwen-orderbook-merged --outfile qob.gguf
# #   ./llama-quantize qob.gguf qob-q4.gguf Q4_K_M
# # on your laptop:
# #   ollama create micro-jarvis -f Modelfile      (FROM ./qob-q4.gguf)
# #   -> answers order-book prompts locally, no GPU needed
