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
        "--diarize",
        action="store_true",
        help="Label speakers with pyannote.audio (requires optional dependencies and a Hugging Face token)",
    )
    parser.add_argument("--num-speakers", type=int, default=None)
    parser.add_argument("--min-speakers", type=int, default=None)
    parser.add_argument("--max-speakers", type=int, default=None)
    parser.add_argument(
        "--speaker-names",
        default=None,
        help="Comma-separated names mapped to SPEAKER_00, SPEAKER_01, and so on",
    )
    parser.add_argument("--hf-token", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--diarization-model",
        default="pyannote/speaker-diarization-community-1",
    )
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


def overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def speaker_for_interval(
    start: float,
    end: float,
    turns: list[dict[str, Any]],
) -> str | None:
    if not turns:
        return None
    ranked = [
        (overlap(start, end, turn["start"], turn["end"]), turn["speaker"])
        for turn in turns
    ]
    best_overlap, best_speaker = max(ranked, key=lambda item: item[0])
    if best_overlap > 0:
        return best_speaker
    midpoint = (start + end) / 2
    nearest = min(
        turns,
        key=lambda turn: abs(midpoint - ((turn["start"] + turn["end"]) / 2)),
    )
    return nearest["speaker"]


def parse_speaker_names(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    names = [name.strip() for name in value.split(",") if name.strip()]
    return {f"SPEAKER_{index:02d}": name for index, name in enumerate(names)}


def apply_speaker_names(
    turns: list[dict[str, Any]],
    names: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {**turn, "speaker": names.get(turn["speaker"], turn["speaker"])}
        for turn in turns
    ]


def hugging_face_token(args: argparse.Namespace) -> str | None:
    token = (
        args.hf_token
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    )
    if token:
        return token
    try:
        from huggingface_hub import get_token

        return get_token()
    except ImportError:
        return None


def diarize_audio(
    media: Path,
    args: argparse.Namespace,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise SystemExit(
            "Speaker diarization dependencies are missing. "
            "Install requirements-diarization.txt or run setup.ps1 -Diarization."
        ) from exc

    token = hugging_face_token(args)
    if not token:
        raise SystemExit(
            "Speaker diarization requires HF_TOKEN. Create a read token at "
            "https://huggingface.co/settings/tokens and accept the model terms at "
            "https://huggingface.co/pyannote/speaker-diarization-community-1."
        )

    print(f"Loading diarization model={args.diarization_model}", flush=True)
    try:
        pipeline = Pipeline.from_pretrained(
            args.diarization_model,
            token=token,
            cache_dir=args.download_root,
        )
    except Exception as exc:
        raise SystemExit(
            f"Could not load diarization model {args.diarization_model}. "
            "Confirm that the Hugging Face token has read access and that the "
            f"model conditions have been accepted. Reason: {exc}"
        ) from exc
    if pipeline is None:
        raise SystemExit(
            f"Could not load diarization model {args.diarization_model}. "
            "Confirm model access on Hugging Face."
        )
    if device == "cuda" and torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))

    diarization_kwargs: dict[str, int] = {}
    if args.num_speakers is not None:
        diarization_kwargs["num_speakers"] = args.num_speakers
    else:
        if args.min_speakers is not None:
            diarization_kwargs["min_speakers"] = args.min_speakers
        if args.max_speakers is not None:
            diarization_kwargs["max_speakers"] = args.max_speakers

    result = pipeline(str(media), **diarization_kwargs)
    annotation = getattr(
        result,
        "exclusive_speaker_diarization",
        getattr(result, "speaker_diarization", result),
    )
    turns = [
        {"start": turn.start, "end": turn.end, "speaker": speaker}
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]
    turns.sort(key=lambda turn: (turn["start"], turn["end"], turn["speaker"]))
    names = parse_speaker_names(args.speaker_names)
    turns = apply_speaker_names(turns, names)
    speakers = sorted({turn["speaker"] for turn in turns})
    metadata = {
        "enabled": True,
        "model": args.diarization_model,
        "speaker_count": len(speakers),
        "speakers": speakers,
        "requested_num_speakers": args.num_speakers,
        "requested_min_speakers": args.min_speakers,
        "requested_max_speakers": args.max_speakers,
        "alignment_timeline": (
            "exclusive"
            if hasattr(result, "exclusive_speaker_diarization")
            else "standard"
        ),
    }
    return turns, metadata


def split_segments_by_speaker(
    segments: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    language: str,
) -> list[dict[str, Any]]:
    split: list[dict[str, Any]] = []
    for segment in segments:
        timed_words = [
            word
            for word in segment.get("words", [])
            if word.get("start") is not None and word.get("end") is not None
        ]
        if not timed_words:
            split.append(
                {
                    **segment,
                    "speaker": speaker_for_interval(
                        segment["start"], segment["end"], turns
                    ),
                }
            )
            continue

        groups: list[dict[str, Any]] = []
        for word in timed_words:
            speaker = speaker_for_interval(word["start"], word["end"], turns)
            if groups and groups[-1]["speaker"] == speaker:
                groups[-1]["words"].append(word)
                groups[-1]["end"] = word["end"]
            else:
                groups.append(
                    {
                        "speaker": speaker,
                        "start": word["start"],
                        "end": word["end"],
                        "words": [word],
                    }
                )

        for group in groups:
            raw_text = "".join(word["word"] for word in group["words"]).strip()
            text = chinese_to_simplified(raw_text) if language == "zh" else raw_text
            split.append(
                {
                    **segment,
                    "start": group["start"],
                    "end": group["end"],
                    "text": text,
                    "raw_text": raw_text if raw_text != text else None,
                    "speaker": group["speaker"],
                    "words": group["words"],
                }
            )

    for index, segment in enumerate(split, start=1):
        segment["id"] = index
    return split


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
    speaker_turns: list[dict[str, Any]] | None = None,
    diarization_metadata: dict[str, Any] | None = None,
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
        "diarization": diarization_metadata or {"enabled": False},
        "speaker_turns": speaker_turns or [],
        "segments": segments,
    }
    (args.output_dir / "meeting.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "transcript.txt").write_text(
        "\n".join(
            f"[{segment['speaker']}] {segment['text']}"
            if segment.get("speaker")
            else segment["text"]
            for segment in segments
        )
        + "\n",
        encoding="utf-8",
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
        speaker = f" {segment['speaker']}" if segment.get("speaker") else ""
        markdown.append(
            f"**S{segment['id']:04d} [{format_timestamp(segment['start'])}"
            f"-{format_timestamp(segment['end'])}]{speaker}** {segment['text']}"
        )
        markdown.append("")
    (args.output_dir / "transcript.md").write_text("\n".join(markdown), encoding="utf-8")

    srt_blocks = []
    for index, segment in enumerate(segments, start=1):
        text = (
            f"[{segment['speaker']}] {segment['text']}"
            if segment.get("speaker")
            else segment["text"]
        )
        srt_blocks.append(
            f"{index}\n{format_timestamp(segment['start'], srt=True)} --> "
            f"{format_timestamp(segment['end'], srt=True)}\n{text}"
        )
    (args.output_dir / "transcript.srt").write_text(
        "\n\n".join(srt_blocks) + "\n", encoding="utf-8"
    )
    if media_info is not None:
        (args.output_dir / "audio-info.json").write_text(
            json.dumps(media_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if speaker_turns:
        (args.output_dir / "speakers.json").write_text(
            json.dumps(
                {
                    "diarization": diarization_metadata,
                    "turns": speaker_turns,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def main() -> None:
    args = parse_args()
    args.media = args.media.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    if not args.media.is_file():
        raise SystemExit(f"Media file not found: {args.media}")
    if args.num_speakers is not None and (
        args.min_speakers is not None or args.max_speakers is not None
    ):
        raise SystemExit(
            "--num-speakers cannot be combined with --min-speakers or --max-speakers."
        )
    for option, value in (
        ("--num-speakers", args.num_speakers),
        ("--min-speakers", args.min_speakers),
        ("--max-speakers", args.max_speakers),
    ):
        if value is not None and value < 1:
            raise SystemExit(f"{option} must be at least 1.")
    if (
        args.min_speakers is not None
        and args.max_speakers is not None
        and args.min_speakers > args.max_speakers
    ):
        raise SystemExit("--min-speakers cannot be greater than --max-speakers.")
    if args.speaker_names and not args.diarize:
        raise SystemExit("--speaker-names requires --diarize.")
    if args.diarize and not hugging_face_token(args):
        raise SystemExit(
            "Speaker diarization requires HF_TOKEN. Create a read token at "
            "https://huggingface.co/settings/tokens and accept the model terms at "
            "https://huggingface.co/pyannote/speaker-diarization-community-1."
        )
    media_info = probe_media(args.media)
    metadata, segments = transcribe(args)
    speaker_turns = None
    diarization_metadata = None
    if args.diarize:
        speaker_turns, diarization_metadata = diarize_audio(
            args.media, args, metadata["device"]
        )
        segments = split_segments_by_speaker(
            segments, speaker_turns, metadata["language"]
        )
    write_outputs(
        args,
        metadata,
        segments,
        media_info,
        speaker_turns=speaker_turns,
        diarization_metadata=diarization_metadata,
    )
    print(f"Meeting package written to: {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
