#!/usr/bin/env python3
"""Qwen2.5-Omni Speech-to-Speech server — run this on a FREE Kaggle GPU.

This hosts the one-model speech-to-speech model. It listens for person-speech
audio and replies with the agent's spoken audio, so your Windows PC does NOT
run any heavy AI.

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
    from transformers import (
        Qwen2_5OmniForConditionalGeneration,
        Qwen2_5OmniProcessor,
    )
    hf_token = get_hf_token()
    print(f"Loading {MODEL_ID} ...")
    model = Qwen2_5OmniForConditionalGeneration.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
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
        inputs = processor(text=text, audios=[audio], return_tensors="pt",
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
        "max_new_tokens": 256,
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
