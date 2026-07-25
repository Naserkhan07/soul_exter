"""LTX-Video: the fastest open text-to-video model for a small GPU.

Lightricks publish a measured figure of **121 frames at 720x480 in under a
minute on an RTX 4060 (8 GB)** for the distilled 2B model, which is the most
credible speed anchor available for consumer hardware.

The speed comes from the VAE, not the step count. LTX compresses
32x32x8 per token against Wan's 8x8x4 — roughly a 1:192 ratio. A 5-second
clip becomes ~6k tokens instead of ~126k, and attention cost grows about
quadratically with tokens. The distilled variant then needs only 8 steps and
no classifier-free guidance.

Requires ``diffusers``, ``transformers`` and a CUDA GPU, all imported lazily.
"""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

from soulclip.providers import (
    GenerationResult,
    PermanentError,
    ProviderError,
    VideoProvider,
)

#: LTX renders at 24fps.
LTX_FPS = 24

#: Verified against the Hugging Face Hub. The 0.9.6-distilled repo that an
#: earlier version referenced does not exist; loading it fails immediately
#: with "model is not cached locally".
KNOWN_MODELS = {
    # Base 2B. Works with the plain LTXPipeline and fits a free T4.
    "ltx2b": "Lightricks/LTX-Video",
    "ltx": "Lightricks/LTX-Video",
    # 0.9.7 distilled — faster, but needs LTXConditionPipeline.
    "ltx097": "Lightricks/LTX-Video-0.9.7-distilled",
    "ltxdistilled": "Lightricks/LTX-Video-0.9.7-distilled",
    "ltx13b": "Lightricks/LTX-Video-0.9.7-distilled",
}

#: Repos whose pipeline class is LTXConditionPipeline rather than LTXPipeline.
_CONDITION_PIPELINE = ("0.9.7", "0.9.8", "distilled")

#: Defaults for the distilled checkpoints, which are trained for these.
DISTILLED_DEFAULTS = {"steps": 8, "guidance": 1.0}


def _resolve(model: str) -> str:
    key = model.lower().replace("-", "").replace("_", "").replace(".", "")
    return KNOWN_MODELS.get(key, model)


def _is_distilled(repo: str) -> bool:
    return "distilled" in repo.lower()


class LtxProvider(VideoProvider):
    """Generate clips with LTX-Video on a CUDA GPU.

    Options:
        steps: Denoising steps (8 for distilled, ~20 for dev).
        guidance: Guidance scale; 1.0 disables CFG and halves the work.
        frames: Frames per clip. LTX wants ``8k+1`` (121, 161, 257).
        height/width: Must be multiples of 32.
        negative: Negative prompt (ignored when guidance is 1.0).
        decode_timestep / image_cond_noise_scale: LTX VAE decode tuning.
    """

    name = "ltx"
    default_model = "ltx2b"

    _pipe: Any = None
    _pipe_key: str | None = None

    # ------------------------------------------------------------------

    def _load(self, on_status=None):
        repo = _resolve(self.model)
        dtype_name = str(self.options.get("dtype", "bf16")).lower()
        key = f"{repo}:{dtype_name}"
        if LtxProvider._pipe is not None and LtxProvider._pipe_key == key:
            return LtxProvider._pipe

        try:
            import torch
            import diffusers
        except ImportError as exc:
            raise PermanentError(
                "The ltx provider needs torch and diffusers:\n"
                "  pip install -U diffusers transformers accelerate imageio-ffmpeg\n"
                f"({exc})"
            ) from exc

        if not torch.cuda.is_available():
            raise PermanentError(
                "No CUDA GPU found. In Colab choose "
                "Runtime > Change runtime type > T4 GPU."
            )

        dtype = {
            "bf16": torch.bfloat16,
            "fp16": torch.float16,
            "fp32": torch.float32,
        }.get(dtype_name, torch.bfloat16)

        if on_status:
            on_status(f"loading {repo} (first run downloads several GB)")

        # The distilled checkpoints ship a different pipeline class, and
        # loading them with LTXPipeline fails on a config mismatch.
        wants_condition = any(tag in repo for tag in _CONDITION_PIPELINE)
        candidates = []
        if wants_condition and hasattr(diffusers, "LTXConditionPipeline"):
            candidates.append(diffusers.LTXConditionPipeline)
        candidates.append(diffusers.LTXPipeline)

        pipe = None
        errors = []
        for cls in candidates:
            try:
                pipe = cls.from_pretrained(repo, torch_dtype=dtype)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{cls.__name__}: {str(exc)[:200]}")

        if pipe is None:
            raise PermanentError(
                f"Could not load {repo}.\n  " + "\n  ".join(errors) +
                "\n\nCheck the model name against "
                "https://huggingface.co/Lightricks"
            )

        if self.options.get("offload", True):
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")

        try:
            pipe.vae.enable_slicing()
            pipe.vae.enable_tiling()
        except Exception:
            pass

        pipe.set_progress_bar_config(disable=True)

        LtxProvider._pipe = pipe
        LtxProvider._pipe_key = key
        return pipe

    @classmethod
    def unload(cls):
        cls._pipe = None
        cls._pipe_key = None
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass

    # ------------------------------------------------------------------

    def _frames_for(self, duration: int) -> int:
        """LTX wants 8k+1 frames. 121 frames at 24fps is ~5 seconds."""
        requested = self.options.get("frames")
        n = int(requested) if requested else int(round(duration * LTX_FPS))
        cap = int(self.options.get("max_frames", 121))
        n = max(9, min(n, cap))
        return int(round((n - 1) / 8)) * 8 + 1

    @staticmethod
    def _round32(value: int) -> int:
        """LTX requires both dimensions to be multiples of 32."""
        return max(32, int(round(value / 32)) * 32)

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        import torch
        from diffusers.utils import export_to_video

        pipe = self._load(on_status=on_status)
        dest.parent.mkdir(parents=True, exist_ok=True)

        repo = _resolve(self.model)
        distilled = _is_distilled(repo)

        frames = self._frames_for(duration)
        steps = int(self.options.get(
            "steps", DISTILLED_DEFAULTS["steps"] if distilled else 20
        ))
        guidance = float(self.options.get(
            "guidance", DISTILLED_DEFAULTS["guidance"] if distilled else 3.0
        ))
        width = self._round32(int(self.options.get("width", 768)))
        height = self._round32(int(self.options.get("height", 512)))
        seed = int(self.options.get("seed", 0))

        style = self.options.get("style", "")
        full_prompt = f"{prompt} {style}".strip() if style else prompt

        negative = self.options.get(
            "negative",
            "worst quality, inconsistent motion, blurry, jittery, distorted",
        )

        if on_status:
            on_status(
                f"{frames}f (~{frames / LTX_FPS:.1f}s) @ {width}x{height}, "
                f"{steps} steps"
                + (", no CFG" if guidance <= 1.0 else f", cfg {guidance}")
            )

        generator = torch.Generator(device="cpu").manual_seed(seed)

        try:
            result = pipe(
                prompt=full_prompt,
                negative_prompt=negative,
                width=width,
                height=height,
                num_frames=frames,
                num_inference_steps=steps,
                guidance_scale=guidance,
                decode_timestep=float(self.options.get("decode_timestep", 0.03)),
                decode_noise_scale=float(
                    self.options.get("decode_noise_scale", 0.025)
                ),
                generator=generator,
            )
        except torch.cuda.OutOfMemoryError as exc:
            self.unload()
            raise ProviderError(
                "GPU out of memory. Try --ltx-frames 81 or a smaller "
                "--width/--height."
            ) from exc

        export_to_video(result.frames[0], str(dest), fps=LTX_FPS)

        if not dest.exists() or dest.stat().st_size < 1024:
            raise ProviderError(f"LTX produced no usable file at {dest}")

        return GenerationResult(
            dest, self.name, repo, None,
            {"frames": frames, "steps": steps, "fps": LTX_FPS,
             "cfg": guidance > 1.0},
        )
