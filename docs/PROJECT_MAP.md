# Project Map

This file is the shortest path to understanding which parts of `PolicyAnalyzerPro` matter for day-to-day work.

## 1. Read These First

If the goal is to understand the real application flow, read files in this order:

1. [main.py](/D:/chapter1/main.py)
2. [ui/main_window.py](/D:/chapter1/ui/main_window.py)
3. [core/nlp_thread.py](/D:/chapter1/core/nlp_thread.py)
4. [core/offline/analyzer.py](/D:/chapter1/core/offline/analyzer.py)
5. [core/result_formatter.py](/D:/chapter1/core/result_formatter.py)

That chain covers application startup, the main desktop workflow, background analysis execution, the offline analysis core, and final report rendering/export.

## 2. High-Value Source Directories

```text
D:/chapter1
|- main.py                  # desktop app entry point
|- core/                    # analysis pipeline, config, routing, formatting
|  `- offline/              # offline analysis engine split by responsibility
|- ui/                      # Qt windows, dialogs, and main interaction flow
|- importers/               # TXT / DOCX / PDF import and OCR fallback
|- config/                  # default JSON config
|- assets/                  # fonts, dictionaries, static assets
|- scripts/                 # build, acceptance, self-check helper scripts
|- tests/                   # regression, smoke, GUI tests
`- docs/                    # architecture, process notes, project map
```

## 3. Core Runtime Flow

```text
main.py
  -> ui/main_window.py
  -> core/analysis_router.py
  -> core/nlp_thread.py
  -> core/offline/analyzer.py
  -> core/result_formatter.py
```

Supplementary branches:

- `importers/` feeds cleaned text into the main analysis flow.
- `core/startup_checks.py` runs startup diagnostics before business actions.
- `config/default_config.json` feeds `core/config.py`.

## 4. What Is Core vs Extension

### Current primary path

These files form the real working product today:

- [main.py](/D:/chapter1/main.py)
- [ui/main_window.py](/D:/chapter1/ui/main_window.py)
- [importers/document_loader.py](/D:/chapter1/importers/document_loader.py)
- [core/config.py](/D:/chapter1/core/config.py)
- [core/nlp_thread.py](/D:/chapter1/core/nlp_thread.py)
- [core/offline/analyzer.py](/D:/chapter1/core/offline/analyzer.py)
- [core/offline/extraction.py](/D:/chapter1/core/offline/extraction.py)
- [core/offline/summaries.py](/D:/chapter1/core/offline/summaries.py)
- [core/result_formatter.py](/D:/chapter1/core/result_formatter.py)
- [core/startup_checks.py](/D:/chapter1/core/startup_checks.py)

### Compatibility facade

- [core/algorithms.py](/D:/chapter1/core/algorithms.py)
  Purpose: keeps the old import path stable while the offline code lives in `core/offline/`.

### New but not dominant

These are important extension points, but they are not the current main business engine:

- [core/analysis_router.py](/D:/chapter1/core/analysis_router.py)
  Purpose: choose `offline / online / hybrid` and handle fallback.
- [core/online_llm/](/D:/chapter1/core/online_llm)
  Purpose: online LLM integration boundary.
- [core/hybrid_pipeline/](/D:/chapter1/core/hybrid_pipeline)
  Purpose: local-plus-online orchestration boundary.
- [core/policy_fetch/](/D:/chapter1/core/policy_fetch)
  Purpose: policy collection boundary, intentionally decoupled from analysis startup.

## 5. Directories Safe To Ignore Most Of The Time

These paths are usually not where feature logic lives:

- `build/`
- `dist/`
- `tmp/`
- `.venv/`
- `.pip-cache/`
- `python313/`
- `_wheel_probe/`
- `.idea/`
- `.vscode/`
- `.codex/`

They are local environment, packaging output, diagnostics, or editor/runtime helpers.

## 6. Root-Level File Meaning

- [README.md](/D:/chapter1/README.md): human-facing project intro and usage guide
- [requirements.txt](/D:/chapter1/requirements.txt): Python dependencies
- [PolicyAnalyzerPro.spec](/D:/chapter1/PolicyAnalyzerPro.spec): PyInstaller packaging spec
- [LICENSE](/D:/chapter1/LICENSE): license text

Files that were not part of the product source have been moved under `tmp/`:

- [deployment-diagnostic-latest.md](/D:/chapter1/tmp/diagnostics/deployment-diagnostic-latest.md)
- [sample.txt](/D:/chapter1/tmp/local-experiments/c-io-sample/sample.txt)
- [test1.c](/D:/chapter1/tmp/local-experiments/c-io-sample/test1.c)

## 7. If The Goal Is To Keep Reading Only Useful Code

Use this order:

1. `main.py`
2. `ui/main_window.py`
3. `importers/document_loader.py`
4. `core/config.py`
5. `core/analysis_router.py`
6. `core/nlp_thread.py`
7. `core/offline/analyzer.py`
8. `core/result_formatter.py`
9. `tests/test_smoke.py`
10. `tests/test_analysis_modes.py`

This sequence filters out most environment noise and gets to the feature code quickly.
