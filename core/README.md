# Core Module Guide

`core/` is now easier to read if treated as three layers.

## 1. Current offline business engine

These files and packages make up the real analysis path that works today:

1. [offline/analyzer.py](/D:/chapter1/core/offline/analyzer.py)
2. [offline/extraction.py](/D:/chapter1/core/offline/extraction.py)
3. [offline/summaries.py](/D:/chapter1/core/offline/summaries.py)
4. [offline/runtime.py](/D:/chapter1/core/offline/runtime.py)
5. [nlp_thread.py](/D:/chapter1/core/nlp_thread.py)
6. [result_formatter.py](/D:/chapter1/core/result_formatter.py)

The old [algorithms.py](/D:/chapter1/core/algorithms.py) file is now only a compatibility facade so existing imports keep working.

## 2. Runtime and app coordination

- [config.py](/D:/chapter1/core/config.py): app config model and runtime path resolution
- [analysis_router.py](/D:/chapter1/core/analysis_router.py): chooses `offline / online / hybrid` and records fallback metadata
- [startup_checks.py](/D:/chapter1/core/startup_checks.py): startup diagnostics and self-checks
- [import_preview.py](/D:/chapter1/core/import_preview.py): import preview support
- [text_cleaner.py](/D:/chapter1/core/text_cleaner.py): shared text normalization helpers

## 3. Extension boundaries

These directories are valid code, but they are not the dominant engine today:

- [online_llm/](/D:/chapter1/core/online_llm): online LLM service boundary
- [hybrid_pipeline/](/D:/chapter1/core/hybrid_pipeline): hybrid orchestration boundary
- [policy_fetch/](/D:/chapter1/core/policy_fetch): policy collection boundary

## 4. Practical rule

If a bug affects current offline analysis, start in `core/offline/` and `importers/document_loader.py` before reading the extension packages.
