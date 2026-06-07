#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
RUNTIME="${MEETING_AUDIO_RUNTIME:-$HOME/.codex/skill-runtimes/meeting-audio-notes}"
SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$PYTHON" -m venv "$RUNTIME"
"$RUNTIME/bin/python" -m pip install --upgrade pip
"$RUNTIME/bin/python" -m pip install -r "$SKILL_ROOT/requirements.txt"
"$RUNTIME/bin/python" -c "import ctranslate2, faster_whisper, opencc, rapidfuzz; print('Runtime ready'); print('CUDA devices:', ctranslate2.get_cuda_device_count())"

printf 'Python: %s\n' "$RUNTIME/bin/python"
printf 'For NVIDIA acceleration, install the CUDA/cuDNN libraries required by CTranslate2.\n'

