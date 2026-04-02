param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipOcr = $false,
    [switch]$SkipBuild = $false
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-ProjectPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }
    return Join-Path $projectRoot $Value
}

Push-Location $projectRoot
try {
    $pythonPath = Resolve-ProjectPath $Python

    Write-Host "Running unit and regression tests..."
    & $pythonPath -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Unit/regression tests failed with exit code $LASTEXITCODE"
    }

    if (-not $SkipOcr) {
        Write-Host "Running OCR acceptance..."
        & $pythonPath scripts/ocr_acceptance.py
        if ($LASTEXITCODE -ne 0) {
            throw "OCR acceptance failed with exit code $LASTEXITCODE"
        }
    }

    if (-not $SkipBuild) {
        Write-Host "Running packaged build validation..."
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "validate_dist.ps1") -Python $pythonPath -Build
        if ($LASTEXITCODE -ne 0) {
            throw "Distribution validation failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host "P0 acceptance completed successfully."
}
finally {
    Pop-Location
}
