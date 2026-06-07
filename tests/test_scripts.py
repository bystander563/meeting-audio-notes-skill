from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()

