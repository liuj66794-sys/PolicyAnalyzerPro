# Tesseract OCR Setup

## Why Codex failed to download it

Two separate issues showed up in this environment:

- The UB Mannheim Windows installer endpoint either returned `403 Forbidden` or timed out.
- The fallback `conda-forge` route worked for `micromamba`, but the large `tesseract` package download to `conda.anaconda.org` did not complete inside this Codex session.

That does not mean your own terminal cannot do it. A normal PyCharm terminal on the same machine often has fewer network restrictions than this session.

## Recommended path: run the setup script in your own terminal

Open a terminal in `D:\chapter1` and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_tesseract_with_micromamba.ps1
```

The script now defaults to the Tsinghua TUNA conda mirror. If `micromamba` has already been downloaded into `D:\chapter1\tools`, the script will reuse it.

If TUNA is slow or unavailable, switch to BFSU with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_tesseract_with_micromamba.ps1 -CondaForgeChannel https://mirrors.bfsu.edu.cn/anaconda/cloud/conda-forge -MicromambaPackageUrl https://mirrors.bfsu.edu.cn/anaconda/cloud/conda-forge/win-64/micromamba-2.5.0-1.tar.bz2
```

## If you want to download the package manually first

1. Download this file to `D:\chapter1\tools\micromamba-2.5.0-1.tar.bz2`

- `https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/win-64/micromamba-2.5.0-1.tar.bz2`

2. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_tesseract_with_micromamba.ps1 -SkipDownload
```

## If you want to manually download only the missing Tesseract package

Right now the workspace already contains `micromamba` and most dependency caches. The main missing artifact is the Tesseract package itself.

1. Download this file to `D:\chapter1\tools\mamba-root\pkgs\tesseract-5.5.2-hfa586c3_0.conda`

- `https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/win-64/tesseract-5.5.2-hfa586c3_0.conda`

2. Then run the setup script in offline mode:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_tesseract_with_micromamba.ps1 -SkipDownload -Offline
```

## If you install Tesseract by some other method

If you already have a working `tesseract.exe`, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_tesseract_cmd.ps1 -TesseractExe "C:\path\to\tesseract.exe"
```

That command validates the binary and writes `tesseract_cmd` into `config/default_config.json`.

## Verification

After installation, verify with:

```powershell
D:\chapter1\.venv\Scripts\python.exe -c "from core.config import load_app_config; from core.startup_checks import run_startup_checks; r=run_startup_checks(load_app_config()); print(r.overall_label); [print(f'{x.key}|{x.status}|{x.summary}') for x in r.results]"
```

You want these two items to become `ok`:

- `ocr_pipeline`
- `ocr_languages`
