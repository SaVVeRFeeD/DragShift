"""Local FFmpeg-backed audio and video conversions and tools."""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from .util import UserError, sibling

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".m4v", ".mpeg", ".mpg"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".aiff", ".wma"}

VIDEO_TARGETS = {"MP4": ".mp4", "MOV": ".mov", "MKV": ".mkv", "WEBM": ".webm",
                 "AVI": ".avi", "GIF": ".gif"}
AUDIO_TARGETS = {"MP3": ".mp3", "M4A": ".m4a", "WAV": ".wav", "FLAC": ".flac",
                 "OGG": ".ogg", "OPUS": ".opus", "AIFF": ".aiff"}
_AUDIO_CODECS = {"MP3": ["-c:a", "libmp3lame", "-q:a", "2"],
                 "M4A": ["-c:a", "aac", "-b:a", "192k"],
                 "WAV": ["-c:a", "pcm_s16le"], "FLAC": ["-c:a", "flac"],
                 "OGG": ["-c:a", "libvorbis", "-q:a", "5"],
                 "OPUS": ["-c:a", "libopus", "-b:a", "160k"],
                 "AIFF": ["-c:a", "pcm_s16be"]}


def ffmpeg_exe() -> str:
    """Use the user's local FFmpeg; do not upload files or fetch binaries at runtime."""
    configured = os.environ.get("DRAGSHIFT_FFMPEG")
    found = configured if configured and Path(configured).is_file() else shutil.which("ffmpeg")
    if not found:
        raise UserError("Audio/video tools need FFmpeg. Install FFmpeg or set DRAGSHIFT_FFMPEG to ffmpeg.exe.")
    return str(found)


def targets_for(cat: str, src_ext: str) -> list[str]:
    ext = src_ext.lower()
    if cat == "video":
        current = ext.lstrip(".").upper()
        targets = list(VIDEO_TARGETS)
        if "MP3" not in targets:
            targets.append("MP3")
        return [t for t in targets if t != current]
    if cat == "audio":
        current = ext.lstrip(".").upper()
        return [t for t in AUDIO_TARGETS if t != current]
    return []


def _output(src: str | Path, label: str, ext: str) -> tuple[Path, Path]:
    out = sibling(src, label, ext=ext)
    temp = out.with_name(f".{out.stem}.{uuid.uuid4().hex}.part{out.suffix}")
    return out, temp


def _run(src: str | Path, label: str, ext: str, *, before_input: list[str] | None = None,
         after_input: list[str] | None = None) -> Path:
    out, temp = _output(src, label, ext)
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    cmd.extend(before_input or [])
    cmd.extend(["-i", str(src)])
    cmd.extend(after_input or [])
    cmd.append(str(temp))
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=None, creationflags=flags)
        if proc.returncode or not temp.is_file() or temp.stat().st_size == 0:
            detail = "\n".join(proc.stderr.strip().splitlines()[-5:])
            raise UserError("FFmpeg could not process this file." + (f"\n{detail}" if detail else ""))
        # On Windows os.rename refuses to overwrite a concurrently-created destination.
        os.rename(temp, out)
        return out
    finally:
        temp.unlink(missing_ok=True)


def convert(src: str | Path, cat: str, target: str) -> list[Path]:
    target = target.upper()
    if cat == "video" and target == "MP3":
        out = _run(src, "", AUDIO_TARGETS[target], after_input=["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-b:a", "192k"])
        return [out]
    if cat == "video" and target in VIDEO_TARGETS:
        ext = VIDEO_TARGETS[target]
        if target == "GIF":
            args = ["-map", "0:v:0", "-vf", "fps=15,scale=640:-1:flags=lanczos", "-loop", "0", "-an"]
        elif target == "WEBM":
            args = ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libvpx-vp9", "-crf", "32",
                    "-b:v", "0", "-c:a", "libopus"]
        elif target == "AVI":
            args = ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "mpeg4", "-q:v", "4",
                    "-c:a", "libmp3lame", "-b:a", "192k"]
        else:
            args = ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "23",
                    "-preset", "medium", "-c:a", "aac", "-b:a", "192k"]
        return [_run(src, "", ext, after_input=args)]
    if cat == "audio" and target in AUDIO_TARGETS:
        return [_run(src, "", AUDIO_TARGETS[target], after_input=["-map", "0:a:0", "-vn", *_AUDIO_CODECS[target]])]
    raise UserError(f"Can't convert {cat} to {target}.")


def compress_video(src: str | Path, crf: int = 28) -> Path:
    return _run(src, "Compressed", ".mp4", after_input=["-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-c:a", "aac",
                "-b:a", "128k", "-movflags", "+faststart"])


def mute_video(src: str | Path) -> Path:
    return _run(src, "Muted", Path(src).suffix.lower(), after_input=["-map", "0:v:0", "-c:v", "copy", "-an"])


def extract_audio(src: str | Path) -> Path:
    return _run(src, "Audio", ".mp3", after_input=["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-b:a", "192k"])


def video_to_gif(src: str | Path, start: float = 0, duration: float = 5) -> Path:
    return _run(src, "GIF", ".gif", before_input=["-ss", str(max(0, start))],
                after_input=["-t", str(max(0.1, min(duration, 30))), "-map", "0:v:0",
                             "-vf", "fps=15,scale=640:-1:flags=lanczos", "-loop", "0", "-an"])


def resize_video(src: str | Path, height: int = 1080) -> Path:
    filt = f"scale=-2:min({height}\\,ih)"
    return _run(src, "Resized", ".mp4", after_input=["-map", "0:v:0", "-map", "0:a:0?",
                "-vf", filt, "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"])


def trim_video(src: str | Path, start: float, duration: float) -> Path:
    return _run(src, "Trimmed", ".mp4", before_input=["-ss", str(max(0, start))],
                after_input=["-t", str(max(0.1, duration)), "-map", "0:v:0", "-map", "0:a:0?",
                             "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "192k"])


def compress_audio(src: str | Path, bitrate: int = 160) -> Path:
    return _run(src, "Compressed", ".mp3", after_input=["-map", "0:a:0", "-vn", "-c:a", "libmp3lame",
                "-b:a", f"{bitrate}k"])


def normalize_audio(src: str | Path) -> Path:
    return _run(src, "Normalized", ".mp3", after_input=["-map", "0:a:0", "-vn", "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "192k"])


def trim_audio(src: str | Path, start: float, duration: float) -> Path:
    return _run(src, "Trimmed", ".mp3", before_input=["-ss", str(max(0, start))],
                after_input=["-t", str(max(0.1, duration)), "-map", "0:a:0", "-vn",
                             "-c:a", "libmp3lame", "-b:a", "192k"])
