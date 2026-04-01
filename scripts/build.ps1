param(
    [string]$Python = "python",
    [switch]$UseVirtualEnv = $false
)

$ErrorActionPreference = "Stop"

# 检查Python版本
$PythonVersion = & $Python --version 2>&1
Write-Host "使用Python版本: $PythonVersion"

# 确保目录存在
if (-not (Test-Path "dist")) {
    New-Item -ItemType Directory -Path "dist" -Force
}

if (-not (Test-Path "build")) {
    New-Item -ItemType Directory -Path "build" -Force
}

# 构建命令
$BuildArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name", "PolicyAnalyzerPro",
    "--add-data", "assets;assets",
    "--add-data", "config;config",
    "--add-data", "models;models",
    "--add-data", "tests;tests",
    "--hidden-import", "sentence_transformers",
    "--hidden-import", "torch",
    "--hidden-import", "transformers",
    "--hidden-import", "pytesseract",
    "--hidden-import", "PySide6",
    "--hidden-import", "PySide6.QtWidgets",
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib",
    "main.py"
)

Write-Host "开始构建..."
& $Python @BuildArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "构建成功！可执行文件位于 dist\PolicyAnalyzerPro 目录"
    
    # 复制必要的文件到输出目录
    if (Test-Path "dist\PolicyAnalyzerPro") {
        # 复制字体文件
        if (Test-Path "assets\fonts") {
            Copy-Item "assets\fonts" "dist\PolicyAnalyzerPro\assets\" -Recurse -Force
        }
        
        # 复制模型目录
        if (Test-Path "models") {
            Copy-Item "models" "dist\PolicyAnalyzerPro\" -Recurse -Force
        }
        
        Write-Host "必要文件已复制到输出目录"
    }
} else {
    Write-Host "构建失败，退出代码: $LASTEXITCODE"
    exit $LASTEXITCODE
}
