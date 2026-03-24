param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

& $Python -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --name PolicyAnalyzerPro \
    --add-data "assets;assets" \
    --add-data "config;config" \
    --add-data "models;models" \
    main.py
