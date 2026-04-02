param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$Build = $false,
    [string]$DistDir = "dist\PolicyAnalyzerPro",
    [string]$SelfCheckJson = "dist\PolicyAnalyzerPro\startup-self-check.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-ProjectPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }
    return Join-Path $projectRoot $Value
}

function Resolve-DistArtifact([string]$DistRoot, [string[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        $path = Join-Path $DistRoot $candidate
        if (Test-Path $path) {
            return $path
        }
    }
    return $null
}

Push-Location $projectRoot
try {
    $pythonPath = Resolve-ProjectPath $Python
    if ($Build) {
        Write-Host "Building distribution..."
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build.ps1") -Python $pythonPath
        if ($LASTEXITCODE -ne 0) {
            throw "Build failed with exit code $LASTEXITCODE"
        }
    }

    $resolvedDistDir = Resolve-ProjectPath $DistDir
    $exePath = Join-Path $resolvedDistDir "PolicyAnalyzerPro.exe"
    if (-not (Test-Path $exePath)) {
        throw "Missing packaged executable: $exePath"
    }

    $requiredArtifacts = @(
        @{ Label = "config"; Candidates = @("config\default_config.json", "_internal\config\default_config.json") },
        @{ Label = "font"; Candidates = @("assets\fonts\simhei.ttf", "_internal\assets\fonts\simhei.ttf") },
        @{ Label = "model_dir"; Candidates = @("models", "_internal\models") }
    )

    foreach ($artifact in $requiredArtifacts) {
        $resolvedPath = Resolve-DistArtifact $resolvedDistDir $artifact.Candidates
        if (-not $resolvedPath) {
            throw "Missing required dist artifact [$($artifact.Label)] under $resolvedDistDir"
        }
        Write-Host "Validated artifact [$($artifact.Label)]: $resolvedPath"
    }

    $reportPath = Resolve-ProjectPath $SelfCheckJson
    Write-Host "Running packaged self-check..."
    & $exePath --self-check --self-check-json $reportPath
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged self-check failed with exit code $LASTEXITCODE"
    }

    Write-Host "Distribution validation passed."
    Write-Host "Self-check JSON: $reportPath"
}
finally {
    Pop-Location
}
