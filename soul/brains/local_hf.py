"""Local open-source LLM cabins (transformers + optional 4-bit bitsandbytes).

This is what actually runs on the Kaggle GPU. Models are loaded lazily, one per
cabin, and shared through a pool when two cabins want the same weights.

Kaggle notes:
  * 2 x Tesla T4, 16 GB each -> 7B/8B models in 4-bit fit on a single card,
    so ``device_map="auto"`` spreads the pool across both GPUs.
  * ``SOUL_LOAD_4BIT=1`` (default) keeps VRAM sane. Set 0 only for tiny models.
  * First run downloads weights to HF_HOME; Kaggle's ``/kaggle/working`` or a
    dataset mount both work (see kaggle/README.md).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import Verdict
from .base import (CabinSpec, build_cabin_prompt, build_ceo_prompt, make_verdict,
                   parse_verdict)

log = logging.getLogger("soul.brains.local")


class ModelPool:
    """Loads and caches HF causal LMs, one entry per model name."""

    def __init__(self, load_in_4bit: bool = True, max_cached: int = 3) -> None:
        self.load_in_4bit = load_in_4bit
        self.max_cached = max_cached
        self._cache: Dict[str, Tuple[Any, Any]] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.load_errors: Dict[str, str] = {}

    # ------------------------------------------------------------------
    def _lock_for(self, name: str) -> threading.Lock:
        with self._guard:
            if name not in self._locks:
                self._locks[name] = threading.Lock()
            return self._locks[name]

    def _evict_if_needed(self) -> None:
        while len(self._cache) > max(0, self.max_cached - 1):
            name, (model, tok) = next(iter(self._cache.items()))
            self._cache.pop(name, None)
            try:
                del model
                import torch

                torch.cuda.empty_cache()
            except Exception:
                pass
            log.info("model pool: evicted %s", name)

    def get(self, name: str, adapter: Optional[str] = None) -> Tuple[Any, Any]:
        """Blocking load (run inside a thread).

        An adapter makes the pool key `model|adapter`: a desk that has been
        trained loads *its own* LoRA on top of the base weights, so two desks
        that share a base model still hold two different opinions.
        """
        key = name if not adapter else f"{name}|{adapter}"
        if key in self._cache:
            return self._cache[key]
        with self._lock_for(key):
            if key in self._cache:
                return self._cache[key]
            self._evict_if_needed()
            model, tok = self._load(name, adapter)
            self._cache[key] = (model, tok)
            return model, tok

    def _load(self, name: str, adapter: Optional[str] = None) -> Tuple[Any, Any]:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        log.info("loading %s ...", name)
        t0 = time.time()
        tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        kwargs: Dict[str, Any] = {
            "device_map": "auto",
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }
        if torch.cuda.is_available():
            kwargs["torch_dtype"] = torch.float16
            if self.load_in_4bit:
                try:
                    from transformers import BitsAndBytesConfig

                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_use_double_quant=True,
                    )
                except Exception as exc:                     # pragma: no cover
                    log.warning("bitsandbytes unavailable (%s); loading fp16", exc)
        else:
            kwargs["torch_dtype"] = torch.float32
        try:
            kwargs["attn_implementation"] = "sdpa"
            model = AutoModelForCausalLM.from_pretrained(name, **kwargs)
        except (TypeError, ValueError):
            kwargs.pop("attn_implementation", None)
            model = AutoModelForCausalLM.from_pretrained(name, **kwargs)
        if adapter:
            # The desk's fine-tune, trained by `python -m soul.train` on its own
            # settled decisions. Same pipeline, same prompts, personalised read.
            try:
                from peft import PeftModel

                model = PeftModel.from_pretrained(model, adapter)
                log.info("loaded LoRA adapter %s on %s", adapter, name)
            except Exception as exc:                            # pragma: no cover
                log.warning("adapter %s failed to load (%s) — base weights only", adapter, exc)
        model.eval()
        log.info("loaded %s in %.1fs", name, time.time() - t0)
        return model, tok


class LocalHFBrain:
    """One cabin, one local model."""

    kind = "local-hf"

    def __init__(self, spec: CabinSpec, pool: ModelPool, model_name: Optional[str] = None,
                 adapters_dir: Optional[str] = None) -> None:
        self.spec = spec
        self.pool = pool
        self.model_name = model_name or spec.model_prefs[0]
        #: the desk's own fine-tune, if the trainer has produced one
        self.adapter: Optional[str] = None
        if adapters_dir:
            path = Path(adapters_dir) / spec.key
            if (path / "adapter_config.json").exists():
                self.adapter = str(path)
        self.semaphore = asyncio.Semaphore(1)   # one generation at a time per cabin
        self.generation_count = 0

    # ------------------------------------------------------------------
    def _build_prompt(self, trade, ctx, prior) -> str:
        if self.spec.is_ceo:
            return build_ceo_prompt(self.spec, trade, prior, ctx)
        return build_cabin_prompt(self.spec, trade, ctx, prior)

    def _render(self, tok, prompt: str) -> str:
        messages = [
            {"role": "system", "content": self.spec.system_prompt},
            {"role": "user", "content": prompt},
        ]
        try:
            return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:                                    # pragma: no cover
            return (f"<|system|>\n{self.spec.system_prompt}\n<|user|>\n{prompt}\n<|assistant|>\n")

    def _generate(self, prompt: str) -> str:
        import torch

        model, tok = self.pool.get(self.model_name, self.adapter)
        text = self._render(tok, prompt)
        inputs = tok(text, return_tensors="pt").to(model.device)
        gen_kwargs: Dict[str, Any] = {
            "max_new_tokens": self.spec.max_new_tokens,
            "do_sample": self.spec.temperature > 0.01,
            "temperature": max(0.01, self.spec.temperature),
            "top_p": 0.9,
            "repetition_penalty": 1.05,
            "pad_token_id": tok.pad_token_id or tok.eos_token_id,
        }
        with torch.inference_mode():
            out = model.generate(**inputs, **gen_kwargs)
        new_tokens = out[0][inputs["input_ids"].shape[-1]:]
        self.generation_count += 1
        return tok.decode(new_tokens, skip_special_tokens=True)

    async def debate(self, topic: str, transcript: List[Dict[str, Any]], kind: str,
                     inner: Dict[str, Any]) -> str:
        """One turn in the debate room, generated by the real model.

        Same weights as the verdict, different prompt: this is the desk the
        trader is carrying the trade *to*, so the debate is a review meeting, not
        a rerun of the vote.
        """
        prompt = self.spec.debate_prompt(topic, transcript, kind,
                                         str(inner.get("to_name", "")),
                                         rules=list(inner.get("rules") or []),
                                         facts=inner)
        async with self.semaphore:
            try:
                text = await asyncio.get_running_loop().run_in_executor(None, self._generate, prompt)
            except Exception as exc:                              # pragma: no cover
                log.warning("%s debate failed: %s", self.spec.key, exc)
                return f"(the {self.spec.label} could not join: {type(exc).__name__})"
        return " ".join(text.strip().split())[:600]

    async def judge(self, trade, ctx: Dict[str, Any], prior: Optional[List[Verdict]] = None,
                    stage: int = 1) -> Verdict:
        prior = prior or []
        prompt = self._build_prompt(trade, ctx, prior)
        t0 = time.time()
        async with self.semaphore:
            try:
                text = await asyncio.get_running_loop().run_in_executor(None, self._generate, prompt)
            except Exception as exc:                          # pragma: no cover
                log.warning("%s generation failed: %s", self.spec.key, exc)
                text = ""
                parsed = {
                    "verdict": "ABSTAIN", "confidence": 30,
                    "reason": f"model error: {type(exc).__name__}",
                    "risk_flags": ["model_error"], "adjustment": {"size_multiplier": 0.0},
                }
                return make_verdict(self.spec, parsed, self.model_name,
                                    int((time.time() - t0) * 1000), stage, trade.id, text)
        parsed = parse_verdict(text)
        if self.spec.is_ceo and parsed["verdict"] == "ABSTAIN":
            parsed["verdict"] = "REJECT" if parsed["confidence"] < 50 else "APPROVE"
        return make_verdict(self.spec, parsed, self.model_name,
                            int((time.time() - t0) * 1000), stage, trade.id, text)