param(
    [Parameter(Mandatory = $true)]
    [string]$TesseractExe,
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $TesseractExe)) {
    throw "Tesseract executable not found: $TesseractExe"
}

Write-Host "Verifying Tesseract binary..."
& $TesseractExe --version
$langOutput = & $TesseractExe --list-langs
$langOutput

$configPath = Join-Path $ProjectRoot 'config\default_config.json'
$pythonScript = @"
import json
from pathlib import Path

config_path = Path(r"$configPath")
tesseract_exe = r"$TesseractExe"

payload = json.loads(config_path.read_text(encoding='utf-8-sig'))
payload['tesseract_cmd'] = tesseract_exe
config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')
"@
$pythonScript | D:\python3.14.3\python.exe -

Write-Host "Updated config/default_config.json"
Write-Host "tesseract_cmd = $TesseractExe"
