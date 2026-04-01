﻿from __future__ import annotations

"""Backward-compatible facade for the offline analysis engine.

The implementation now lives under `core.offline.*` so the current import path
can stay stable while the offline pipeline becomes easier to navigate.
"""

from core.offline import (
    PolicyReportAnalyzer,
    PreparedText,
    ProgressCallback,
    initialize_runtime_environment,
)

__all__ = [
    "PreparedText",
    "ProgressCallback",
    "PolicyReportAnalyzer",
    "initialize_runtime_environment",
]
