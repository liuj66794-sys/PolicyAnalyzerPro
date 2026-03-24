from __future__ import annotations

import re

from core.config import AppConfig, DEFAULT_CONFIG


class TextCleaner:
    """
    Clean policy-oriented long-form text while preserving paragraph structure
    for downstream sentence-level comparison and topic extraction.
    """

    _sentence_splitter = re.compile(r"(?<=[。！？；;!?])")

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or DEFAULT_CONFIG
        self._line_noise_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.config.noise_patterns
        ]
        self._inline_noise_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.config.inline_noise_patterns
        ]

    def clean_text(self, text: str) -> str:
        if not text:
            return ""

        normalized = self._normalize_whitespace(text)
        kept_lines: list[str] = []

        for raw_line in normalized.splitlines():
            line = raw_line.strip()
            if not line or self._is_noise_line(line):
                continue

            cleaned_line = self._strip_inline_noise(line)
            cleaned_line = self._normalize_inline_spacing(cleaned_line)
            if cleaned_line:
                kept_lines.append(cleaned_line)

        cleaned_text = "\n".join(kept_lines)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
        return cleaned_text.strip()

    def clean_paragraphs(self, text: str) -> list[str]:
        cleaned = self.clean_text(text)
        if not cleaned:
            return []
        return [paragraph.strip() for paragraph in cleaned.split("\n") if paragraph.strip()]

    def split_sentences(self, text: str) -> list[str]:
        cleaned = self.clean_text(text)
        if not cleaned:
            return []

        sentences: list[str] = []
        for paragraph in cleaned.splitlines():
            chunks = self._sentence_splitter.split(paragraph)
            for chunk in chunks:
                sentence = chunk.strip()
                if sentence:
                    sentences.append(sentence)
        return sentences

    def _is_noise_line(self, line: str) -> bool:
        return any(pattern.search(line) for pattern in self._line_noise_patterns)

    def _strip_inline_noise(self, line: str) -> str:
        cleaned = line
        for pattern in self._inline_noise_patterns:
            cleaned = pattern.sub("", cleaned)
        return cleaned.strip(" \t-:：|")

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u3000", " ").replace("\xa0", " ")
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        return text.strip()

    @staticmethod
    def _normalize_inline_spacing(text: str) -> str:
        text = re.sub(r"\s*([，。！？；：、])\s*", r"\1", text)
        text = re.sub(r"\s*([()（）])\s*", r"\1", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()
