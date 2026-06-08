# Runtime

Create an isolated runtime with the bundled setup script.

Windows:

```powershell
.\scripts\setup.ps1 -Gpu -Diarization
```

Linux or macOS:

```bash
DIARIZATION=1 ./scripts/setup.sh
```

Default runtime paths:

```text
Windows: ~/.codex/skill-runtimes/meeting-audio-notes/Scripts/python.exe
POSIX:   ~/.codex/skill-runtimes/meeting-audio-notes/bin/python
```

Override the location with the `Runtime` PowerShell parameter or the `MEETING_AUDIO_RUNTIME` environment variable.

## Dependencies

The base runtime installs:

- `faster-whisper` for transcription;
- `opencc-python-reimplemented` for traditional-to-simplified Chinese normalization;
- `rapidfuzz` for error-tolerant follow-up search;
- `socksio` for Hugging Face downloads through SOCKS proxies.

On Windows, `setup.ps1 -Gpu` also installs the NVIDIA cuBLAS and cuDNN wheels. The transcription script adds their DLL directories automatically.

`-Diarization` installs `pyannote.audio`. When combined with `-Gpu`, the setup script installs matching PyTorch 2.11 CUDA 12.6 wheels instead of PyPI's CPU defaults. Speaker diarization may add several gigabytes of packages and model files.

The transcription script disables optional pyannote usage telemetry by default with `PYANNOTE_METRICS_ENABLED=0`. Users can explicitly override this environment variable.

On Linux, install the CUDA and cuDNN versions required by CTranslate2 through the operating system or NVIDIA packages.

## Model Cache

Models are downloaded on first use. `large-v3` needs several gigabytes. The
configured cache is shared by Whisper and pyannote.

Set a cache on a drive with enough free space:

```powershell
.\scripts\setup.ps1 -Gpu -ModelCache "D:\models\meeting-audio-notes"
```

Or set `MEETING_AUDIO_MODEL_CACHE` manually. The transcription script also accepts `--download-root`.

## CPU Fallback

If CUDA cannot load:

```text
--device cpu --compute-type int8
```

FFmpeg and FFprobe are recommended for media inspection and broad codec support. PyAV, installed through `faster-whisper`, handles common audio decoding.

## Hugging Face Access

Speaker diarization uses `pyannote/speaker-diarization-community-1`.

1. Create a Hugging Face account.
2. Accept the model conditions at:
   `https://huggingface.co/pyannote/speaker-diarization-community-1`
3. Create a read token at:
   `https://huggingface.co/settings/tokens`
4. Log in through the official CLI:

```powershell
& "$HOME\.codex\skill-runtimes\meeting-audio-notes\Scripts\hf.exe" auth login
```

Paste the token only into the CLI prompt. Do not send it through chat.

Alternatively, set it without writing the token into the skill or meeting package:

```powershell
[Environment]::SetEnvironmentVariable("HF_TOKEN", "hf_...", "User")
```

Restart the terminal or Codex after setting the user environment variable. Never commit or paste the token into meeting output.
