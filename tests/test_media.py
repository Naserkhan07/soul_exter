import subprocess
from pathlib import Path

from shorts_bot.media import MediaProcessor


def test_high_quality_blurred_background_render_command(tmp_path: Path) -> None:
    processor = MediaProcessor(
        video_layout="blurred_background",
        video_crf=18,
        video_preset="slow",
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(command, 0, "", "")

    processor._run = fake_run  # type: ignore[method-assign]
    output = tmp_path / "short.mp4"
    processor.render_short(tmp_path / "source.mkv", output, 0, 30)

    command = commands[0]
    assert "-filter_complex" in command
    assert any("boxblur=30:2" in value for value in command)
    assert command[command.index("-crf") + 1] == "18"
    assert command[command.index("-preset") + 1] == "slow"
    assert "fps=30" not in " ".join(command)
    assert output.exists()


def test_center_crop_has_no_blurred_background(tmp_path: Path) -> None:
    processor = MediaProcessor(video_layout="center_crop", video_crf=18, video_preset="slow")
    commands: list[list[str]] = []

    def fake_run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(command, 0, "", "")

    processor._run = fake_run  # type: ignore[method-assign]
    output = tmp_path / "short.mp4"
    processor.render_short(tmp_path / "source.mkv", output, 0, 30)

    command_text = " ".join(commands[0])
    assert "-vf" in commands[0]
    assert "crop=1080:1920" in command_text
    assert "boxblur" not in command_text
