#!/usr/bin/env python3
"""Transcribe media into a durable, timestamped meeting package."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def chinese_to_simplified(text: str) -> str:
    try:
        from opencc import OpenCC

        return OpenCC("t2s").convert(text)
    except ImportError:
        return text


def configured_model_cache() -> str | None:
    value = os.environ.get("MEETING_AUDIO_MODEL_CACHE")
    if value or os.name != "nt":
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, "MEETING_AUDIO_MODEL_CACHE")[0]
    except (FileNotFoundError, OSError):
        return None


def add_windows_nvidia_dll_dirs() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    candidates: list[Path] = []
    for entry in sys.path:
        base = Path(entry)
        candidates.extend(
            [
                base / "nvidia" / "cublas" / "bin",
                base / "nvidia" / "cudnn" / "bin",
            ]
        )
    for candidate in candidates:
        if candidate.is_dir():
            os.add_dll_directory(str(candidate))
            os.environ["PATH"] = f"{candidate}{os.pathsep}{os.environ.get('PATH', '')}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path, help="Audio or video file")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--language", default=None)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--compute-type", default=None)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--vad-filter", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--initial-prompt", default=None)
    parser.add_argument(
        "--download-root",
        type=Path,
        default=configured_model_cache(),
        help="Model cache directory; defaults to MEETING_AUDIO_MODEL_CACHE or the Hugging Face cache",
    )
    return parser.parse_args()


def detect_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def format_timestamp(seconds: float, srt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def probe_media(media: Path) -> dict[str, Any] | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(media),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def transcribe(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    add_windows_nvidia_dll_dirs()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "faster-whisper is not installed. Read references/runtime.md and use the isolated runtime."
        ) from exc

    device = detect_device(args.device)
    compute_type = args.compute_type or ("float16" if device == "cuda" else "int8")
    download_root = None
    if args.download_root:
        download_root = str(args.download_root.expanduser().resolve())
        Path(download_root).mkdir(parents=True, exist_ok=True)
    print(f"Loading model={args.model} device={device} compute_type={compute_type}", flush=True)
    model = WhisperModel(
        args.model,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )
    raw_segments, info = model.transcribe(
        str(args.media),
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=args.vad_filter,
        word_timestamps=True,
        initial_prompt=args.initial_prompt,
        condition_on_previous_text=True,
    )

    segments: list[dict[str, Any]] = []
    for index, segment in enumerate(raw_segments, start=1):
        raw_text = segment.text.strip()
        if not raw_text:
            continue
        text = chinese_to_simplified(raw_text) if info.language == "zh" else raw_text
        words = [
            {
                "start": word.start,
                "end": word.end,
                "word": word.word,
                "probability": word.probability,
            }
            for word in (segment.words or [])
        ]
        segments.append(
            {
                "id": index,
                "start": segment.start,
                "end": segment.end,
                "text": text,
                "raw_text": raw_text if raw_text != text else None,
                "speaker": None,
                "avg_logprob": segment.avg_logprob,
                "no_speech_prob": segment.no_speech_prob,
                "words": words,
            }
        )
        print(
            f"[{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}] {text}",
            flush=True,
        )

    metadata = {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "duration_after_vad": info.duration_after_vad,
        "model": args.model,
        "device": device,
        "compute_type": compute_type,
    }
    return metadata, segments


def write_outputs(
    args: argparse.Namespace,
    metadata: dict[str, Any],
    segments: list[dict[str, Any]],
    media_info: dict[str, Any] | None,
) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    canonical = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(args.media.resolve()),
            "name": args.media.name,
            "size_bytes": args.media.stat().st_size,
        },
        "transcription": metadata,
        "segments": segments,
    }
    (args.output_dir / "meeting.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "transcript.txt").write_text(
        "\n".join(segment["text"] for segment in segments) + "\n", encoding="utf-8"
    )

    markdown = [
        f"# Transcript: {args.media.name}",
        "",
        f"- Language: `{metadata['language']}`",
        f"- Duration: `{format_timestamp(metadata['duration'])}`",
        f"- Model: `{metadata['model']}`",
        "",
    ]
    for segment in segments:
        markdown.append(
            f"**S{segment['id']:04d} [{format_timestamp(segment['start'])}"
            f"-{format_timestamp(segment['end'])}]** {segment['text']}"
        )
        markdown.append("")
    (args.output_dir / "transcript.md").write_text("\n".join(markdown), encoding="utf-8")

    srt_blocks = []
    for index, segment in enumerate(segments, start=1):
        srt_blocks.append(
            f"{index}\n{format_timestamp(segment['start'], srt=True)} --> "
            f"{format_timestamp(segment['end'], srt=True)}\n{segment['text']}"
        )
    (args.output_dir / "transcript.srt").write_text(
        "\n\n".join(srt_blocks) + "\n", encoding="utf-8"
    )
    if media_info is not None:
        (args.output_dir / "audio-info.json").write_text(
            json.dumps(media_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main() -> None:
    args = parse_args()
    args.media = args.media.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    if not args.media.is_file():
        raise SystemExit(f"Media file not found: {args.media}")
    media_info = probe_media(args.media)
    metadata, segments = transcribe(args)
    write_outputs(args, metadata, segments, media_info)
    print(f"Meeting package written to: {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
