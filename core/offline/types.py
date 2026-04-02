from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class PreparedText:
    raw_text: str
    cleaned_text: str
    paragraphs: list[str]
    sentences: list[str]
    metadata: dict[str, Any]
