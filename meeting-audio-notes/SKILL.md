---
name: meeting-audio-notes
description: Transcribe uploaded audio or video recordings, produce structured Chinese meeting minutes, preserve timestamped evidence, and answer follow-up questions about decisions, speakers, numbers, deadlines, disagreements, and other details. Use for meeting recordings, interviews, lectures, calls, voice memos, podcasts, and requests such as 音频转文字, 会议纪要, 总结录音, 谁说了什么, or 追问录音细节. Supports mp3, wav, m4a, mp4, mov, webm, flac, ogg, and other FFmpeg-readable media.
---

# Meeting Audio Notes

Turn each recording into a durable meeting package. Treat the timestamped transcript as the source of truth; summaries are derived views, not replacements for evidence.

## Workflow

1. Locate every user-provided audio or video file. Do not assume an attachment is already transcribed.
2. Run `scripts/transcribe_audio.py` for each recording. Use the runtime Python documented in `references/runtime.md`. Prefer `outputs/<source-stem>-meeting-notes` in a Codex workspace; otherwise use a sibling `<source-stem>-meeting-notes` directory.
3. Read `meeting.json` and `transcript.md`. Correct only obvious proper-name or domain-term errors; never silently invent unclear speech.
4. Create `minutes.md` in the same meeting directory using `references/minutes-template.md`.
5. Tell the user where the meeting package was saved and give the concise summary in chat.
6. On later questions, reuse the existing package. Search first with `scripts/search_transcript.py`; inspect the surrounding timestamped segments before answering.

## Transcribe

Use a separate output directory per recording:

```powershell
& $runtimePython scripts/transcribe_audio.py `
  "C:\path\meeting.m4a" `
  --output-dir "C:\path\meeting-notes" `
  --model large-v3 `
  --language zh
```

Model selection:

- Use `large-v3` by default for Chinese, mixed Chinese-English, names, and noisy meetings.
- Use `medium` when the user prioritizes speed or the recording is long and clear.
- Omit `--language` only when the language is genuinely unknown.
- Pass `--device cpu --compute-type int8` only after CUDA fallback is needed.

The script writes:

- `meeting.json`: canonical metadata and timestamped segments.
- `transcript.md`: human-readable transcript with segment IDs and timestamps.
- `transcript.txt`: plain transcript.
- `transcript.srt`: subtitle file.
- `audio-info.json`: FFprobe metadata when available.

Do not delete the meeting package after summarizing. It is the memory used for follow-up questions.

## Write Minutes

Use `references/minutes-template.md`. Include only sections supported by the recording. Prefer:

- executive summary;
- key topics and conclusions;
- decisions;
- action items with owner and deadline;
- risks, blockers, and open questions;
- important numbers, dates, names, and links;
- timestamped highlights.

Add timestamp links as plain citations such as `[00:18:42]` or ranges such as `[00:18:42-00:19:15]`. Mark uncertain content as `待确认`, including uncertain speaker identity, owner, deadline, names, and numbers.

Speaker labels from basic transcription may be unavailable. Never infer identity from ordering alone. If the user needs diarization, explain that it is an optional second-stage enhancement and ask for known participant names only when mapping anonymous speakers matters.

## Answer Follow-Up Questions

Search the canonical package:

```powershell
& $runtimePython scripts/search_transcript.py `
  "C:\path\meeting-notes\meeting.json" `
  "预算 交付 截止时间" `
  --context 2
```

Then answer with:

1. a direct answer;
2. timestamped evidence;
3. uncertainty or conflicting statements, if any.

For questions about exact wording, names, amounts, dates, negation, or responsibility, inspect neighboring segments rather than relying on one search hit. Distinguish:

- `明确说过`: directly supported by transcript;
- `可以推断`: inference from multiple passages;
- `录音未提及/无法确认`: no adequate evidence.

Never claim access to details that were not transcribed or retained. If recognition is doubtful, quote only a short phrase and label it `转写可能有误`.

For natural-language questions, derive two to four compact searches before concluding that evidence is absent. Include key entities plus likely meeting terms or synonyms, for example `供应商 接口 文档 风险` or `张伟 负责人 截止日期`. The search script includes fuzzy matching for minor ASR errors, but nearby context remains mandatory.

## Multiple Recordings

Keep one canonical package per file. When producing a combined summary, identify the source recording in every important citation. Do not merge contradictory decisions without noting chronology.

## Runtime

Read `references/runtime.md` when dependencies are missing, CUDA fails, model download fails, or the runtime must be recreated.
