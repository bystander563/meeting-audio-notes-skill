param(
    [switch]$Gpu,
    [switch]$Diarization,
    [string]$Python = "python",
    [string]$Runtime = "$HOME\.codex\skill-runtimes\meeting-audio-notes",
    [string]$ModelCache
)

$ErrorActionPreference = "Stop"
$skillRoot = Split-Path -Parent $PSScriptRoot

& $Python -m venv $Runtime
$runtimePython = Join-Path $Runtime "Scripts\python.exe"
& $runtimePython -m pip install --upgrade pip
& $runtimePython -m pip install -r (Join-Path $skillRoot "requirements.txt")

if ($Gpu) {
    & $runtimePython -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
}

if ($Diarization) {
    if ($Gpu) {
        & $runtimePython -m pip install `
            "torch==2.11.0" "torchaudio==2.11.0" `
            --index-url "https://download.pytorch.org/whl/cu126"
    }
    & $runtimePython -m pip install -r (Join-Path $skillRoot "requirements-diarization.txt")
}

if ($ModelCache) {
    New-Item -ItemType Directory -Force -Path $ModelCache | Out-Null
    [Environment]::SetEnvironmentVariable(
        "MEETING_AUDIO_MODEL_CACHE",
        (Resolve-Path $ModelCache).Path,
        "User"
    )
}

& $runtimePython -c "import ctranslate2, faster_whisper, opencc, rapidfuzz; print('Runtime ready'); print('CUDA devices:', ctranslate2.get_cuda_device_count())"
if ($Diarization) {
    & $runtimePython -c "import pyannote.audio, torch; print('Diarization ready'); print('Torch CUDA:', torch.cuda.is_available())"
}
Write-Output "Python: $runtimePython"
