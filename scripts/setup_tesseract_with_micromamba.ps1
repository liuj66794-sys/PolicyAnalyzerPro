param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$CondaForgeChannel = 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge',
    [string]$MicromambaPackageUrl = 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/win-64/micromamba-2.5.0-1.tar.bz2',
    [string]$MicromambaPackagePath = '',
    [switch]$SkipDownload,
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($MicromambaPackagePath)) {
    $MicromambaPackagePath = Join-Path $ProjectRoot 'tools\micromamba-2.5.0-1.tar.bz2'
}

$toolsRoot = Join-Path $ProjectRoot 'tools'
$micromambaRoot = Join-Path $toolsRoot 'micromamba'
$mambaRoot = Join-Path $toolsRoot 'mamba-root'
$ocrEnv = Join-Path $toolsRoot 'ocr-env'
$micromambaExe = Join-Path $micromambaRoot 'Library\bin\micromamba.exe'
$tesseractExe = Join-Path $ocrEnv 'Library\bin\tesseract.exe'
$configPath = Join-Path $ProjectRoot 'config\default_config.json'

New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
New-Item -ItemType Directory -Force -Path $mambaRoot | Out-Null

if (-not (Test-Path $MicromambaPackagePath)) {
    if ($SkipDownload) {
        throw "Micromamba package not found: $MicromambaPackagePath"
    }
    Write-Host "Downloading micromamba package..."
    Invoke-WebRequest -Uri $MicromambaPackageUrl -OutFile $MicromambaPackagePath
}

if (-not (Test-Path $micromambaExe)) {
    Write-Host "Extracting micromamba..."
    New-Item -ItemType Directory -Force -Path $micromambaRoot | Out-Null
    & tar -xf $MicromambaPackagePath -C $micromambaRoot
}

if (-not (Test-Path $micromambaExe)) {
    throw "micromamba.exe not found after extraction: $micromambaExe"
}

$env:MAMBA_ROOT_PREFIX = $mambaRoot
$env:MAMBA_PKGS_DIRS = Join-Path $mambaRoot 'pkgs'
$env:CONDA_PKGS_DIRS = $env:MAMBA_PKGS_DIRS

if (-not (Test-Path $tesseractExe)) {
    if (Test-Path $ocrEnv) {
        Remove-Item -Recurse -Force $ocrEnv
    }

    $args = @(
        'create',
        '-y',
        '-p', $ocrEnv,
        '--root-prefix', $mambaRoot,
        '--override-channels',
        '-c', $CondaForgeChannel,
        'tesseract'
    )
    if ($Offline) {
        $args += '--offline'
    }

    Write-Host "Creating local OCR environment..."
    & $micromambaExe @args
}

if (-not (Test-Path $tesseractExe)) {
    throw "tesseract.exe not found after install: $tesseractExe"
}

Write-Host "Verifying Tesseract..."
& $tesseractExe --version
$langOutput = & $tesseractExe --list-langs
$langOutput

$pythonScript = @"
import json
from pathlib import Path

config_path = Path(r"$configPath")
tesseract_exe = r"$tesseractExe"

payload = json.loads(config_path.read_text(encoding='utf-8-sig'))
payload['tesseract_cmd'] = tesseract_exe
config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')
"@
$pythonScript | D:\python3.14.3\python.exe -

Write-Host "Updated config/default_config.json"
Write-Host "tesseract_cmd = $tesseractExe"
