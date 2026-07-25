"""Wan text-to-video running locally on a GPU (built for Google Colab).

This is the free path to *real* AI video: Colab hands you a T4 for nothing,
Wan 2.1 T2V 1.3B fits in its 15 GB of VRAM, and soulclip drives the loop.

The model is loaded once and reused for every scene — loading takes a few
minutes, so reloading per clip would dominate the run.

Requires ``diffusers``, ``transformers``, ``torch`` and a CUDA GPU. Those
are pre-installed or one ``pip install`` away in Colab, so they are
imported lazily and are not dependencies of soulclip itself.
"""

from __future__ import annotations

import gc
import os
from pathlib import Path
from typing import Any

from soulclip.providers import (
    GenerationResult,
    PermanentError,
    ProviderError,
    VideoProvider,
)

#: Model ids that are known to work, smallest first.
KNOWN_MODELS = {
    "wan1.3b": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    "wan14b": "Wan-AI/Wan2.1-T2V-14B-Diffusers",
}

#: Wan generates at a fixed frame rate; clip length is set by frame count.
WAN_FPS = 16

#: Step-distilled LoRAs. These are the single biggest speed win available:
#: they cut denoising to ~4 steps *and* are trained for guidance 1.0, which
#: removes classifier-free guidance. CFG runs the model twice per step, so
#: dropping it halves the cost again — together roughly 10x fewer forward
#: passes than the 20-step default.
SPEED_LORAS = {
    "causvid": {
        "repo": "Kijai/WanVideo_comfy",
        "file": "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors",
        "steps": 4,
        "guidance": 1.0,
        "strength": 0.8,
        "note": "CausVid 1.3B — 4 steps, no CFG",
    },
}


def _resolve(model: str) -> str:
    return KNOWN_MODELS.get(model.lower().replace("-", "").replace("_", ""), model)


class WanProvider(VideoProvider):
    """Generate clips with a local Wan model on a CUDA GPU.

    Intended to run *inside* Colab, where soulclip and the GPU sit on the
    same machine. On a free T4 expect roughly 2-5 minutes per 4-second
    480p clip with the default settings.

    Options:
        steps: Denoising steps. 20-25 is good; 8-12 is much faster and
            noticeably softer.
        guidance: Classifier-free guidance scale.
        frames: Frames per clip. Wan wants ``4k+1`` (33, 49, 65, 81).
        height/width: 480p is what the 1.3B model was trained for.
        negative: Negative prompt.
        offload: Move submodules to CPU between steps to save VRAM.
        dtype: "bf16", "fp16" or "fp32".
    """

    name = "wan"
    default_model = "wan1.3b"

    # Set once the pipeline is built, so it survives across scenes.
    _pipe: Any = None
    _pipe_key: str | None = None

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load(self, on_status=None):
        key = (f"{self.model}:{self.options.get('dtype', 'bf16')}"
               f":{self.options.get('speed_lora') or ''}")
        if WanProvider._pipe is not None and WanProvider._pipe_key == key:
            return WanProvider._pipe

        try:
            import torch
            from diffusers import AutoencoderKLWan, WanPipeline
        except ImportError as exc:
            raise PermanentError(
                "The wan provider needs torch and diffusers:\n"
                "  pip install -U diffusers transformers accelerate ftfy\n"
                f"({exc})"
            ) from exc

        if not torch.cuda.is_available():
            raise PermanentError(
                "No CUDA GPU found. The wan provider needs a GPU — in Colab "
                "choose Runtime > Change runtime type > T4 GPU."
            )

        repo = _resolve(self.model)
        dtype_name = str(self.options.get("dtype", "bf16")).lower()
        dtype = {
            "bf16": torch.bfloat16,
            "fp16": torch.float16,
            "fp32": torch.float32,
        }.get(dtype_name, torch.bfloat16)

        if on_status:
            on_status(f"loading {repo} (first run downloads ~6 GB)")

        # The VAE is kept in fp32: Wan's VAE produces artefacts in fp16.
        vae = AutoencoderKLWan.from_pretrained(
            repo, subfolder="vae", torch_dtype=torch.float32
        )
        pipe = WanPipeline.from_pretrained(repo, vae=vae, torch_dtype=dtype)

        if self.options.get("offload", True):
            # Keeps peak VRAM within a free T4's 15 GB.
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")

        try:
            pipe.vae.enable_slicing()
            pipe.vae.enable_tiling()
        except Exception:
            pass  # older diffusers

        self._apply_speed_lora(pipe, on_status=on_status)

        pipe.set_progress_bar_config(disable=True)

        WanProvider._pipe = pipe
        WanProvider._pipe_key = key
        return pipe

    def _apply_speed_lora(self, pipe, on_status=None):
        """Attach a step-distilled LoRA, if one was requested."""
        name = self.options.get("speed_lora")
        if not name:
            return

        spec = SPEED_LORAS.get(str(name).lower())
        if spec is None:
            raise PermanentError(
                f"Unknown speed LoRA {name!r}. Available: "
                f"{', '.join(sorted(SPEED_LORAS))}"
            )

        if on_status:
            on_status(f"loading {spec['note']}")

        try:
            pipe.load_lora_weights(
                spec["repo"], weight_name=spec["file"], adapter_name="speed"
            )
            pipe.set_adapters(
                ["speed"],
                adapter_weights=[float(
                    self.options.get("lora_strength", spec["strength"])
                )],
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"Could not load the {name} LoRA ({exc}). Install peft "
                "(`pip install -U peft`) or drop --fast."
            ) from exc

        # The distilled schedule only holds at its trained settings, so
        # override steps/guidance unless the user was explicit.
        self.options.setdefault("steps", spec["steps"])
        self.options.setdefault("guidance", spec["guidance"])

    @classmethod
    def unload(cls):
        """Free the model and its VRAM."""
        cls._pipe = None
        cls._pipe_key = None
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _frames_for(self, duration: int) -> int:
        """Wan wants 4k+1 frames; convert seconds to the nearest valid count.

        Also caps the count: attention is computed across all frames at
        once, so a long clip will exhaust a free T4's VRAM. Anything longer
        is better produced as several shots, which the pipeline already
        stitches together.
        """
        requested = self.options.get("frames")
        n = int(requested) if requested else int(round(duration * WAN_FPS))

        cap = int(self.options.get("max_frames", 81))  # ~5s at 16fps
        n = max(9, min(n, cap))

        # Snap to the nearest 4k+1 rather than always rounding down.
        return int(round((n - 1) / 4)) * 4 + 1

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        import torch
        from diffusers.utils import export_to_video

        pipe = self._load(on_status=on_status)
        dest.parent.mkdir(parents=True, exist_ok=True)

        frames = self._frames_for(duration)
        steps = int(self.options.get("steps", 20))
        guidance = float(self.options.get("guidance", 5.0))
        height = int(self.options.get("height", 480))
        width = int(self.options.get("width", 832))
        seed = int(self.options.get("seed", 0))

        negative = self.options.get(
            "negative",
            "blurry, low quality, distorted, watermark, text, static, "
            "overexposed, jpeg artifacts, deformed limbs, extra fingers",
        )

        style = self.options.get("style", "")
        full_prompt = f"{prompt} {style}".strip() if style else prompt

        if on_status:
            secs = frames / WAN_FPS
            on_status(f"{frames} frames (~{secs:.1f}s) @ {width}x{height}, {steps} steps")

        generator = torch.Generator(device="cpu").manual_seed(seed)

        try:
            result = pipe(
                prompt=full_prompt,
                negative_prompt=negative,
                height=height,
                width=width,
                num_frames=frames,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=generator,
            )
        except torch.cuda.OutOfMemoryError as exc:
            self.unload()
            raise ProviderError(
                "GPU ran out of memory. Try --wan-frames 33, a smaller "
                "--height/--width, or restart the runtime."
            ) from exc

        video = result.frames[0]
        export_to_video(video, str(dest), fps=WAN_FPS)

        if not dest.exists() or dest.stat().st_size < 1024:
            raise ProviderError(f"Wan produced no usable file at {dest}")

        return GenerationResult(
            dest, self.name, _resolve(self.model), None,
            {"frames": frames, "steps": steps, "fps": WAN_FPS},
        )


def gpu_report() -> str:
    """One-line description of the GPU, for the notebook to print."""
    try:
        import torch
    except ImportError:
        return "torch not installed"
    if not torch.cuda.is_available():
        return "No CUDA GPU — switch the Colab runtime to T4 GPU"
    props = torch.cuda.get_device_properties(0)
    return f"{props.name}, {props.total_memory / 1e9:.1f} GB VRAM"
