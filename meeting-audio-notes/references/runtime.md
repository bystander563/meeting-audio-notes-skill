# Runtime

Create an isolated runtime with the bundled setup script.

Windows:

```powershell
.\scripts\setup.ps1 -Gpu
```

Linux or macOS:

```bash
./scripts/setup.sh
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

On Linux, install the CUDA and cuDNN versions required by CTranslate2 through the operating system or NVIDIA packages.

## Model Cache

Models are downloaded on first use. `large-v3` needs several gigabytes.

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

