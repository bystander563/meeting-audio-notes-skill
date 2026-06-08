from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "meeting-audio-notes" / "scripts"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transcribe = load_module("transcribe_audio", "transcribe_audio.py")
search = load_module("search_transcript", "search_transcript.py")


class TranscriptionHelpersTest(unittest.TestCase):
    def test_timestamp_formats(self):
        self.assertEqual(transcribe.format_timestamp(3661.234), "01:01:01.234")
        self.assertEqual(transcribe.format_timestamp(1.25, srt=True), "00:00:01,250")

    def test_chinese_is_normalized_but_original_can_be_preserved(self):
        raw = "今天確認項目預算"
        simplified = transcribe.chinese_to_simplified(raw)
        self.assertEqual(simplified, "今天确认项目预算")
        self.assertNotEqual(raw, simplified)

    def test_speaker_names_are_mapped_in_order(self):
        names = transcribe.parse_speaker_names("张伟, 李娜")
        self.assertEqual(names["SPEAKER_00"], "张伟")
        self.assertEqual(names["SPEAKER_01"], "李娜")

    def test_hugging_face_token_uses_environment(self):
        args = SimpleNamespace(hf_token=None)
        with patch.dict("os.environ", {"HF_TOKEN": "hf_test"}, clear=False):
            self.assertEqual(transcribe.hugging_face_token(args), "hf_test")

    def test_word_level_speaker_alignment_splits_one_segment(self):
        segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 4.0,
                "text": "你好收到",
                "raw_text": None,
                "speaker": None,
                "words": [
                    {"start": 0.0, "end": 1.0, "word": "你好", "probability": 1.0},
                    {"start": 2.0, "end": 3.0, "word": "收到", "probability": 1.0},
                ],
            }
        ]
        turns = [
            {"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
            {"start": 1.5, "end": 4.0, "speaker": "SPEAKER_01"},
        ]
        split = transcribe.split_segments_by_speaker(segments, turns, "zh")
        self.assertEqual(len(split), 2)
        self.assertEqual(split[0]["speaker"], "SPEAKER_00")
        self.assertEqual(split[0]["text"], "你好")
        self.assertEqual(split[1]["speaker"], "SPEAKER_01")
        self.assertEqual(split[1]["text"], "收到")

    def test_interval_alignment_uses_largest_overlap(self):
        turns = [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 4.0, "speaker": "SPEAKER_01"},
        ]
        self.assertEqual(
            transcribe.speaker_for_interval(0.5, 2.5, turns),
            "SPEAKER_01",
        )

    def test_probe_media_returns_ffprobe_metadata(self):
        sample = Path(__file__).resolve().parents[2] / "meeting-audio-test" / "sample.wav"
        if not sample.exists():
            self.skipTest("Local end-to-end audio fixture is unavailable")
        metadata = transcribe.probe_media(sample)
        self.assertIsNotNone(metadata)
        self.assertIn("format", metadata)

    def test_diarization_prefers_exclusive_timeline(self):
        class Timeline:
            def __init__(self, speaker):
                self.speaker = speaker

            def itertracks(self, yield_label=False):
                turn = SimpleNamespace(start=0.0, end=2.0)
                yield turn, "track", self.speaker

        class FakePipeline:
            def to(self, device):
                self.device = device

            def __call__(self, media, **kwargs):
                return SimpleNamespace(
                    speaker_diarization=Timeline("STANDARD"),
                    exclusive_speaker_diarization=Timeline("SPEAKER_00"),
                )

        args = SimpleNamespace(
            hf_token="hf_test",
            diarization_model="pyannote/test",
            num_speakers=1,
            min_speakers=None,
            max_speakers=None,
            speaker_names=None,
            download_root=Path("model-cache"),
        )
        with patch(
            "pyannote.audio.Pipeline.from_pretrained",
            return_value=FakePipeline(),
        ) as from_pretrained:
            turns, metadata = transcribe.diarize_audio(
                Path("meeting.wav"), args, "cpu"
            )
        from_pretrained.assert_called_once_with(
            "pyannote/test",
            token="hf_test",
            cache_dir=Path("model-cache"),
        )
        self.assertEqual(turns[0]["speaker"], "SPEAKER_00")
        self.assertEqual(metadata["alignment_timeline"], "exclusive")

    def test_speaker_outputs_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "meeting.wav"
            media.write_bytes(b"RIFF")
            output = root / "notes"
            args = SimpleNamespace(media=media, output_dir=output)
            metadata = {
                "language": "zh",
                "duration": 2.0,
                "model": "test",
            }
            segments = [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.0,
                    "text": "你好",
                    "speaker": "SPEAKER_00",
                    "words": [],
                }
            ]
            turns = [
                {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}
            ]
            diarization = {
                "enabled": True,
                "speaker_count": 1,
                "speakers": ["SPEAKER_00"],
            }
            transcribe.write_outputs(
                args,
                metadata,
                segments,
                media_info=None,
                speaker_turns=turns,
                diarization_metadata=diarization,
            )
            meeting = json.loads(
                (output / "meeting.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                meeting["segments"][0]["speaker"], "SPEAKER_00"
            )
            self.assertTrue((output / "speakers.json").exists())
            self.assertIn(
                "[SPEAKER_00] 你好",
                (output / "transcript.txt").read_text(encoding="utf-8"),
            )


class TranscriptSearchTest(unittest.TestCase):
    def write_meeting(self, directory: Path) -> Path:
        meeting = {
            "schema_version": 1,
            "segments": [
                {"id": 1, "start": 0.0, "end": 4.0, "text": "今天确认三个事项", "speaker": None},
                {"id": 2, "start": 4.0, "end": 8.0, "text": "张伟负责准备演示版本", "speaker": None},
                {"id": 3, "start": 8.0, "end": 12.0, "text": "截止日期是六月十五日下午六点", "speaker": None},
                {"id": 4, "start": 12.0, "end": 16.0, "text": "当前风险是工应商接口文档没有交付", "speaker": None},
            ],
        }
        path = directory / "meeting.json"
        path.write_text(json.dumps(meeting, ensure_ascii=False), encoding="utf-8")
        return path

    def test_exact_search_prints_neighboring_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            meeting_path = self.write_meeting(Path(temp))
            argv = [str(meeting_path), "张伟 截止日期", "--context", "1"]
            original = search.parse_args
            search.parse_args = lambda: type(
                "Args",
                (),
                {"meeting_json": meeting_path, "query": argv[1], "context": 1, "limit": 10},
            )()
            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    search.main()
            finally:
                search.parse_args = original
            text = output.getvalue()
            self.assertIn("张伟负责准备演示版本", text)
            self.assertIn("截止日期是六月十五日下午六点", text)

    def test_fuzzy_search_tolerates_one_wrong_chinese_character(self):
        segment = {"text": "当前风险是工应商接口文档没有交付"}
        terms = search.tokens("供应商")
        self.assertGreater(search.score_segment(segment, terms), 0)

    def test_search_matches_speaker_label(self):
        segment = {
            "speaker": "SPEAKER_01",
            "text": "我负责演示版本",
        }
        terms = search.tokens("SPEAKER_01")
        self.assertGreater(search.score_segment(segment, terms), 0)


if __name__ == "__main__":
    unittest.main()
