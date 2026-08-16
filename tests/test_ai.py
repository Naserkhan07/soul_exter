from pathlib import Path

from shorts_bot.ai import normalize_plan
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
            "selection_reason": "Self-contained explanation",
        },
        source(),
        target_duration=25,
    )

    assert plan.start_seconds == 44.2
    assert plan.duration_seconds == 26
    assert plan.title == "A strong moment"
    assert "Source: A useful source — Original Creator" in plan.description
    assert "https://youtu.be/example" in plan.description
    assert "#Shorts" in plan.description


def test_clamps_invalid_timing_to_video() -> None:
    plan = normalize_plan(
        {"start_seconds": 999, "duration_seconds": 12, "title": "Moment"},
        source(duration=22),
        target_duration=25,
    )

    assert plan.duration_seconds == 22
    assert plan.start_seconds == 0
