#!/usr/bin/env python3
"""Qwen2.5-Omni Speech-to-Speech server — run this on a FREE Kaggle GPU.

This hosts the one-model speech-to-speech model. It listens for person-speech
audio and replies with the agent's spoken audio, so your Windows PC does NOT
run any heavy AI.

Model ID: Qwen/Qwen2.5-Omni-3B   (NO '-Instruct' suffix — that ID does not exist)

Requires a RECENT `transformers` (>= 4.51; use the latest). Older versions fail
with "'Qwen2_5OmniTalkerConfig' object has no attribute 'pad_token_id'". Upgrade
with:  pip install -U transformers accelerate bitsandbytes

Endpoint:
    POST /sts   multipart  file=<person speech WAV/FLAC>
                            system=<system prompt text>
                            history=<json list of prior turns>
    -> JSON     {"text": "<understood text>", "audio_b64": "<reply audio>",
                 "language": "auto", "sample_rate": 24000}

HOW TO USE ON KAGGLE (free):
  1. Copy scripts/kaggle/qwen_omni_server.ipynb into a Kaggle Notebook,
     "Accelerator = GPU T4 x2 (16GB)", turn off internet is not needed.
  2. Run all cells. The last cell starts this server and opens a public
     tunnel, printing a URL like https://xxxx.tunnel.ai.
  3. Copy that URL into config `sts.qwen_kaggle.url` (or the qwen_url key).
  4. On your PC run:  python main.py --sts --audio person_speech.wav

The Qwen2.5-Omni-3B model (4-bit) is the smallest native speech-to-speech
Qwen. There is NO 1B/2B Qwen speech-to-speech model — 3B is the smallest.
"""

from __future__ import annotations

import base64
import io
import json
import os

import torch

MODEL_ID = os.environ.get("QWEN_OMNI_MODEL", "Qwen/Qwen2.5-Omni-3B")


# ------------------------------------------------------------------ setup
def get_hf_token():
    """Optional Hugging Face token for gated models.

    The model ID is Qwen/Qwen2.5-Omni-3B (NO '-Instruct' suffix — that ID does
    not exist). Some Qwen models are gated; if yours is, export HF_TOKEN (or set
    it as a Kaggle Secret named HF_TOKEN) after accepting the model's license.
    For non-gated models a token is not required.
    """
    return os.environ.get("HF_TOKEN", "").strip() or None


def load_model():
    import transformers as _tf
    _ver = tuple(int(x) for x in _tf.__version__.split(".")[:3])
    if _ver < (4, 51, 0):
        raise RuntimeError(
            f"transformers {_tf.__version__} is too old for Qwen2.5-Omni. "
            "Run: pip install -U 'transformers>=4.55.0' accelerate bitsandbytes, "
            "then restart your kernel/process and reload."
        )
    from transformers import (
        AutoConfig,
        Qwen2_5OmniForConditionalGeneration,
        Qwen2_5OmniProcessor,
        BitsAndBytesConfig,
    )
    hf_token = get_hf_token()
    print(f"Loading {MODEL_ID} ...")
    # Some transformers versions ship a TalkerConfig WITHOUT pad_token_id, which
    # crashes with 'Qwen2_5OmniTalkerConfig' has no attribute 'pad_token_id'.
    # Patch every sub-config before loading the weights (harmless if present).
    config = AutoConfig.from_pretrained(MODEL_ID, trust_remote_code=True, token=hf_token)
    for _sub in ("talker_config", "thinker_config", "text_config"):
        _sc = getattr(config, _sub, None)
        if _sc is not None and not hasattr(_sc, "pad_token_id"):
            _sc.pad_token_id = getattr(config, "pad_token_id", 151643)
            print("patched", _sub, ".pad_token_id")
    # 4-bit quantization is ESSENTIAL: bf16 of this ~6B model uses ~12GB, which
    # leaves no room for the audio-codec (DiT) generation -> CUDA out of memory.
    bnb = BitsAndBytesConfig(load_in_4bit=True,
                             bnb_4bit_compute_dtype=torch.float16,
                             bnb_4bit_quant_type="nf4")
    model = Qwen2_5OmniForConditionalGeneration.from_pretrained(
        MODEL_ID,
        config=config,
        quantization_config=bnb,
        device_map="auto",
        trust_remote_code=True,
        token=hf_token,
    )
    processor = Qwen2_5OmniProcessor.from_pretrained(
        MODEL_ID, trust_remote_code=True, token=hf_token)
    return model, processor


def load_audio_bytes(raw: bytes, sample_rate: int = 16000):
    """Decode uploaded WAV/FLAC -> float32 mono waveform at sample_rate."""
    import librosa
    y, sr = librosa.load(io.BytesIO(raw), sr=sample_rate, mono=True)
    return y, sr


# ------------------------------------------------------------------ app
def make_app(model, processor):
    from fastapi import FastAPI, File, Form, UploadFile
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Qwen Omni STS")

    @app.get("/health")
    def health():
        return {"status": "ok", "model": MODEL_ID}

    @app.post("/sts")
    async def sts(file: UploadFile = File(...),
                  system: str = Form(""),
                  history: str = Form("[]")):
        raw = await file.read()
        audio, sr = load_audio_bytes(raw)
        try:
            hist = json.loads(history or "[]")
        except Exception:
            hist = []

        # Build the Qwen chat message.
        # The user turn contains the audio + a short instruction.
        user_prompt = (
            "This is a phone conversation. Reply aloud in the SAME language "
            "the speaker used. Answer from the provided context only. "
            "Keep it short and natural."
        )
        messages = [{"role": "system", "content": system}]
        for h in hist:
            role = "assistant" if h.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": h.get("text", "")})
        messages.append({
            "role": "user",
            "content": [{"type": "audio", "audio_url": "uploaded.wav"},
                        {"type": "text", "text": user_prompt}],
        })

        text = processor.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=True)
        inputs = processor(text=text, audio=[audio], return_tensors="pt",
                           padding=True)
        inputs = {k: v.to(model.device) if torch.is_tensor(v) else v
                  for k, v in inputs.items()}

        with torch.no_grad():
            out = model.generate(**inputs, **gen_kwargs(), return_audio=True)

        reply_text = out["text"]
        if isinstance(reply_text, list):
            reply_text = reply_text[0]
        reply_text = reply_text.split("<|im_end|>")[0].strip()

        reply_audio = out.get("audio")
        audio_b64 = ""
        sr_out = 24000
        if reply_audio is not None:
            audio = reply_audio[0].float().cpu().numpy()
            sr_out = out.get("sampling_rate")
            audio_b64 = base64.b64encode(audio.tobytes()).decode()

        return JSONResponse({
            "text": reply_text,
            "audio_b64": audio_b64,
            "sample_rate": int(sr_out),
            "language": "auto",
        })

    return app


def gen_kwargs():
    return {
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "do_sample": True,
        "max_new_tokens": 160,
    }


# ------------------------------------------------------------------ run
def main():
    model, processor = load_model()
    app = make_app(model, processor)

    # Use the public tunnel (Kaggle/Colab style) or plain uvicorn on localhost.
    mode = os.environ.get("STS_TUNNEL", "auto")
    if mode in ("auto", "ngrok"):
        try:
            from pyngrok import ngrok
            # Set your ngrok authtoken (free account) via the NGROK_AUTHTOKEN
            # env/secret, or edit the literal below.
            token = os.environ.get("NGROK_AUTHTOKEN", "").strip()
            if not token:
                token = "PASTE_YOUR_NGROK_AUTHTOKEN_HERE"
            if token and "PASTE_" not in token:
                ngrok.set_auth_token(token)
            else:
                raise SystemExit(
                    "Set NGROK_AUTHTOKEN (or paste your token in this file) "
                    "to open the public tunnel."
                )
            port = 8501
            app_path = app  # type: ignore[assignment]
            # Run uvicorn in a thread, then open the tunnel.
            import threading
            import uvicorn
            config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
            server = uvicorn.Server(config)
            t = threading.Thread(target=server.run, daemon=True)
            t.start()
            url = ngrok.connect(port, bind_tls=True).public_url
            print("\n========== QWEN OMNI STS READY ==========")
            print(f"HEALTH: {url}/health")
            print(f"STS   : {url}/sts")
            print(f"Put this URL in config sts.qwen_kaggle.url = {url}/sts")
            print("===========================================")
            try:
                server_thread = threading.enumerate()
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
        except ImportError as e:
            print("No ngrok — falling back to plain uvicorn (not internet-visible).", e)
            import uvicorn
            uvicorn.run(app, host="0.0.0.0", port=8501)
    else:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8501)


if __name__ == "__main__":
    main()
