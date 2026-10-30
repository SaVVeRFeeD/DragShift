"""FFmpeg-backed media operations. Tests skip when FFmpeg is not installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from dragshift import media
from dragshift.util import category


@pytest.fixture
def clip(tmp_path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is not installed")
    path = tmp_path / "sample.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=size=320x180:rate=12", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=44100", "-t", "1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        pytest.skip("FFprobe is not installed")
    data = subprocess.check_output([ffprobe, "-v", "error", "-show_streams", "-show_format",
                                    "-of", "json", str(path)], text=True)
    return json.loads(data)


def test_media_categories_and_targets():
    assert category("clip.MP4") == "video"
    assert category("song.WAV") == "audio"
    assert "MP3" in media.targets_for("video", ".mp4")
    assert "MP4" not in media.targets_for("video", ".mp4")
    assert "FLAC" in media.targets_for("audio", ".mp3")


def test_video_conversions_and_tools(clip):
    mkv = media.convert(clip, "video", "MKV")[0]
    mp3 = media.convert(clip, "video", "MP3")[0]
    gif = media.video_to_gif(clip, duration=0.5)
    resized = media.resize_video(clip, 144)
    muted = media.mute_video(clip)
    assert mkv.is_file() and mkv.suffix == ".mkv"
    assert mp3.is_file() and probe(mp3)["streams"][0]["codec_type"] == "audio"
    assert Image.open(gif).format == "GIF"
    data = probe(resized)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert video["height"] == 144
    assert not any(s["codec_type"] == "audio" for s in probe(muted)["streams"])
    assert all(".part" not in p.name for p in (mkv, mp3, gif, resized, muted))


def test_audio_conversion_and_tools(clip):
    mp3 = media.extract_audio(clip)
    flac = media.convert(mp3, "audio", "FLAC")[0]
    normalized = media.normalize_audio(flac)
    trimmed = media.trim_audio(flac, 0, 0.4)
    assert probe(mp3)["streams"][0]["codec_name"] == "mp3"
    assert probe(flac)["streams"][0]["codec_name"] == "flac"
    assert probe(normalized)["streams"][0]["codec_name"] == "mp3"
    duration = float(probe(trimmed)["format"]["duration"])
    assert 0.2 <= duration <= 0.7
