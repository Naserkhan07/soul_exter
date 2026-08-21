"""
The Qwen brain — pluggable LLM backends behind one tiny interface.

    brain = get_brain()          # picks backend from config.BRAIN_BACKEND
    raw   = brain.generate_json(system_prompt, user_prompt)

Backends
--------
TransformersBrain : loads Qwen 2.5 3B Instruct locally (Kaggle GPU).
OpenAICompatBrain : talks to any OpenAI-compatible server (Ollama, vLLM,
                    llama.cpp server, LM Studio) so the heavy model can run
                    anywhere.
HeuristicBrain    : deterministic rule engine. Zero GPU. Used for local
                    development/testing of the full pipeline and as an
                    automatic fallback when no model is available.
"""

import json
import logging
import re

import config

log = logging.getLogger("brain")


# ---------------------------------------------------------------------------
# JSON extraction helper — models love to wrap JSON in prose/fences.
# ---------------------------------------------------------------------------
def extract_json(text: str) -> dict:
    if not text:
        return {}
    # strip code fences
    text = re.sub(r"```(?:json)?", "", text)
    # find the first balanced {...}
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # try relaxed fixes: trailing commas
                    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return {}
    return {}


# ---------------------------------------------------------------------------
# Backend: local transformers (Kaggle GPU)
# ---------------------------------------------------------------------------
class TransformersBrain:
    def __init__(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        kwargs = {"device_map": "auto", "torch_dtype": "auto"}
        if config.QWEN_LOAD_IN_4BIT:
            try:
                from transformers import BitsAndBytesConfig

                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                )
            except Exception:  # bitsandbytes unavailable -> full precision
                log.warning("bitsandbytes unavailable, loading without 4-bit")

        log.info("Loading %s ...", config.QWEN_MODEL_ID)
        self.tokenizer = AutoTokenizer.from_pretrained(config.QWEN_MODEL_ID)
        self.model = AutoModelForCausalLM.from_pretrained(
            config.QWEN_MODEL_ID, **kwargs
        )

    def generate_json(self, system: str, user: str) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        out = self.model.generate(
            **inputs,
            max_new_tokens=config.QWEN_MAX_NEW_TOKENS,
            temperature=config.QWEN_TEMPERATURE,
            do_sample=config.QWEN_TEMPERATURE > 0,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        completion = self.tokenizer.decode(
            out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True
        )
        return extract_json(completion)


# ---------------------------------------------------------------------------
# Backend: OpenAI-compatible HTTP API (Ollama / vLLM / llama.cpp ...)
# ---------------------------------------------------------------------------
class OpenAICompatBrain:
    def __init__(self):
        import requests  # noqa: F401  (validated import)

        self.base = config.BRAIN_API_BASE.rstrip("/")
        self.key = config.BRAIN_API_KEY
        self.model = config.BRAIN_API_MODEL

    def generate_json(self, system: str, user: str) -> dict:
        import requests

        resp = requests.post(
            f"{self.base}/chat/completions",
            headers={"Authorization": f"Bearer {self.key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": config.QWEN_TEMPERATURE,
                "max_tokens": config.QWEN_MAX_NEW_TOKENS,
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return extract_json(content)


# ---------------------------------------------------------------------------
# Backend: deterministic heuristic (no GPU, always available)
# ---------------------------------------------------------------------------
class HeuristicBrain:
    """
    Rule engine that mimics the qualification output shape.

    It reads the same evidence dict the LLM would receive (it is embedded in
    the user prompt as JSON) and scores it with config.SCORE_WEIGHTS. This is
    what makes the whole pipeline runnable and testable with zero GPU cost —
    then you flip BRAIN_BACKEND=transformers on Kaggle for the real Qwen.
    """

    def generate_json(self, system: str, user: str) -> dict:
        evidence = self._parse_evidence(user)
        website = evidence.get("website_analysis") or {}
        social = evidence.get("social") or {}
        signals = evidence.get("signals") or {}
        contacts = evidence.get("contacts_found") or {}

        problems, needs = [], {}
        score = 0
        w = config.SCORE_WEIGHTS

        has_site = bool(evidence.get("website"))
        if not has_site:
            problems.append("no website found")
            needs["website"] = "high"
            score += w["website_problem"]
        elif website.get("reachable") is False:
            problems.append(
                f"website unreachable ({website.get('error') or website.get('status')})")
            needs["website"] = "high"
            needs["technical_support"] = "medium"
            score += w["website_problem"]
        else:
            site_issues = 0
            if website.get("https") is False:
                problems.append("website not using HTTPS")
                site_issues += 1
            if website.get("mobile_friendly") is False:
                problems.append("website not mobile friendly")
                site_issues += 1
            if website.get("outdated_design"):
                problems.append("outdated website design")
                site_issues += 1
            if (website.get("load_time_seconds") or 0) > 5:
                problems.append("slow page load")
                site_issues += 1
            if site_issues:
                needs["website_redesign"] = "high" if site_issues >= 2 else "medium"
                score += min(w["website_problem"],
                             w["website_problem"] * site_issues // 2 + 5)

            seo_issues = 0
            if not website.get("title"):
                problems.append("missing page title")
                seo_issues += 1
            if not website.get("meta_description"):
                problems.append("missing meta description")
                seo_issues += 1
            if not website.get("h1_count"):
                problems.append("no H1 heading")
                seo_issues += 1
            if (website.get("word_count") or 0) < 150:
                problems.append("thin page content")
                seo_issues += 1
            if seo_issues:
                needs["seo"] = "high" if seo_issues >= 3 else "medium"
                needs["local_seo"] = "medium"
                score += min(w["weak_seo"], 4 * seo_issues)

            if not website.get("has_cta"):
                problems.append("no clear call-to-action")
                needs["digital_marketing"] = "medium"
                score += 5

        # Social presence
        if social.get("profiles_found") == 0 or not social:
            problems.append("no visible social media presence")
            needs["social_media"] = "high"
            score += w["inactive_social"]
        elif social.get("inactive"):
            problems.append("social media appears inactive")
            needs["social_media"] = "medium"
            score += w["inactive_social"] // 2

        # Explicit demand (e.g. from Reddit / stated need)
        if signals.get("explicit_demand"):
            problems.append(f"explicit demand: {signals['explicit_demand']}")
            needs["digital_marketing"] = "high"
            score += w["explicit_demand"]

        # Business quality (reviews / rating / established)
        reviews = signals.get("review_count") or 0
        rating = signals.get("rating") or 0
        if reviews >= 50 and rating >= 4.0:
            score += w["business_quality"]
        elif reviews >= 10:
            score += w["business_quality"] // 2

        # Marketing problem umbrella
        if len(problems) >= 3:
            score += w["marketing_problem"]
            needs.setdefault("digital_marketing", "medium")
        elif len(problems) >= 1:
            score += w["marketing_problem"] // 2

        # Contact availability
        if any(contacts.get(k) for k in ("phone", "email", "whatsapp")):
            score += w["contact_availability"]
        elif contacts.get("website") or contacts.get("linkedin"):
            score += w["contact_availability"] // 2

        score = max(0, min(100, score))
        recommended = [s for s, lvl in needs.items() if lvl in ("medium", "high")]

        return {
            "qualified": score >= config.MIN_LEAD_SCORE_TO_SAVE,
            "lead_score": score,
            "needs": needs,
            "detected_problems": problems,
            "recommended_services": recommended,
            "reason": self._reason(problems, reviews, rating, score),
        }

    @staticmethod
    def _parse_evidence(user_prompt: str) -> dict:
        start = user_prompt.find("{")
        # evidence json ends before "SCORING GUIDE"
        end = user_prompt.find("SCORING GUIDE")
        blob = user_prompt[start:end if end > 0 else None]
        return extract_json(blob)

    @staticmethod
    def _reason(problems, reviews, rating, score) -> str:
        parts = []
        if reviews:
            parts.append(f"established business ({reviews} reviews, {rating}★)")
        if problems:
            parts.append("issues: " + "; ".join(problems[:4]))
        parts.append(f"rule-based score {score}")
        return ". ".join(parts).capitalize()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_brain = None


def get_brain():
    global _brain
    if _brain is not None:
        return _brain

    backend = config.BRAIN_BACKEND.lower()
    try:
        if backend == "transformers":
            _brain = TransformersBrain()
        elif backend == "openai":
            _brain = OpenAICompatBrain()
        else:
            _brain = HeuristicBrain()
    except Exception as exc:  # model failed to load -> keep pipeline alive
        log.warning("Brain backend '%s' failed (%s); using HeuristicBrain",
                    backend, exc)
        _brain = HeuristicBrain()
    return _brain
