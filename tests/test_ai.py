from pathlib import Path
from types import SimpleNamespace

import httpx
from groq import APIStatusError, RateLimitError

from shorts_bot.ai import AIPlanner, compact_transcript, normalize_plan
from shorts_bot.models import SourceVideo


def source(duration: float = 120) -> SourceVideo:
    return SourceVideo(
        path=Path("source.mp4"),
        source_url="https://youtu.be/example",
        video_id="example",
        title="A useful source",
        uploader="Original Creator",
        duration_seconds=duration,
    )


def test_normalizes_ai_plan_and_adds_attribution() -> None:
    plan = normalize_plan(
        {
            "start_seconds": 44.2,
            "duration_seconds": 26,
            "title": "  A   strong   moment  ",
            "description": "The key idea in a few seconds. #Learning",
            "instagram_caption": "A quick explanation worth saving. #Learning",
            "selection_reason": "Self-contained explanation",
        },
        source(),
        target_duration=25,
    )

    assert plan.start_seconds == 44.2
    assert plan.duration_seconds == 26
    assert plan.title == "A strong moment #Shorts"
    assert "Source: A useful source — Original Creator" in plan.description
    assert "https://youtu.be/example" in plan.description
    assert "#Shorts" in plan.description
    assert "A quick explanation worth saving" in plan.instagram_caption
    assert "Credit: Original Creator" in plan.instagram_caption
    assert "#Reels" in plan.instagram_caption


async def test_retries_with_smaller_transcript_when_prompt_is_too_large() -> None:
    prompt_sizes: list[int] = []

    class FakeCompletions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            prompt_sizes.append(len(kwargs["messages"][1]["content"]))
            if len(prompt_sizes) == 1:
                response = httpx.Response(
                    413,
                    request=httpx.Request("POST", "https://api.groq.com/test"),
                )
                raise APIStatusError("request too large", response=response, body={})
            message = SimpleNamespace(
                content=(
                    '{"start_seconds": 1, "duration_seconds": 25, "title": "Title", '
                    '"description": "Description", "instagram_caption": "Caption"}'
                )
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    planner = AIPlanner(
        api_key="test-key",
        model="small-model",
        fallback_model="small-model",
        transcription_model="whisper-large-v3-turbo",
        max_transcript_chars=16_000,
    )
    planner.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    async def fake_transcribe(_audio_path: Path) -> str:
        return "\n".join(f"[{i}-{i + 1}] Segment {i}" for i in range(3000))

    planner._transcribe = fake_transcribe  # type: ignore[method-assign]
    plan = await planner.create_plan(Path("unused.mp3"), source())

    assert plan.start_seconds == 1
    assert len(prompt_sizes) == 2
    assert prompt_sizes[1] < prompt_sizes[0]


async def test_uses_fallback_model_when_primary_is_rate_limited() -> None:
    requested_models: list[str] = []

    class FakeCompletions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            requested_models.append(kwargs["model"])
            if kwargs["model"] == "large-model":
                response = httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://api.groq.com/test"),
                )
                raise RateLimitError("daily limit", response=response, body={})
            message = SimpleNamespace(content='{"start_seconds": 1}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    planner = AIPlanner(
        api_key="test-key",
        model="large-model",
        fallback_model="small-model",
        transcription_model="whisper-large-v3-turbo",
    )
    planner.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    payload = await planner._request_plan("prompt")

    assert payload == {"start_seconds": 1}
    assert requested_models == ["large-model", "small-model"]


def test_compacts_long_transcript_across_full_timeline() -> None:
    transcript = "\n".join(
        f"[{index:.2f}-{index + 1:.2f}] Segment {index}" for index in range(2000)
    )

    compacted = compact_transcript(transcript, max_chars=8_000, candidate_blocks=8)

    assert len(compacted) <= 8_000
    assert "TIMELINE OMITTED" in compacted
    assert "Segment 0" in compacted
    assert "Segment 1999" in compacted


def test_clamps_invalid_timing_to_video() -> None:
    plan = normalize_plan(
        {"start_seconds": 999, "duration_seconds": 12, "title": "Moment"},
        source(duration=22),
        target_duration=25,
    )

    assert plan.duration_seconds == 22
    assert plan.start_seconds == 0
