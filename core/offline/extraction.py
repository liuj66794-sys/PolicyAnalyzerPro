from __future__ import annotations

import os
import re
from statistics import mean
from typing import Any

from .runtime import initialize_runtime_environment
from .types import PreparedText


class ExtractionMixin:
    def prepare_text(self, text: str) -> PreparedText:
        cleaned = self.cleaner.clean_text(text)
        paragraphs = [line.strip() for line in cleaned.splitlines() if line.strip()]
        sentences = self._split_sentences_from_cleaned(cleaned)
        metadata = self.extract_metadata(cleaned)
        return PreparedText(
            raw_text=text,
            cleaned_text=cleaned,
            paragraphs=paragraphs,
            sentences=sentences,
            metadata=metadata,
        )

    def extract_metadata(self, text: str) -> dict[str, Any]:
        if not text:
            return {"meeting_labels": [], "years": []}

        meeting_labels: list[str] = []
        seen_labels: set[str] = set()

        for pattern in self._metadata_patterns:
            for match in pattern.finditer(text):
                label = match.group(1).strip()
                if label not in seen_labels:
                    seen_labels.add(label)
                    meeting_labels.append(label)

        years: list[str] = []
        seen_years: set[str] = set()
        for match in re.finditer(r"(20\d{2}年)", text):
            year = match.group(1)
            if year not in seen_years:
                seen_years.add(year)
                years.append(year)

        return {
            "meeting_labels": meeting_labels,
            "years": years,
        }

    def extract_new_terms(self, text: str, top_k: int | None = None) -> list[dict[str, Any]]:
        cleaned = self.cleaner.clean_text(text)
        if not cleaned:
            return []

        self._ensure_jieba_ready()
        limit = top_k or self.config.tfidf_top_k
        raw_keywords = self._jieba_analyse.extract_tags(
            cleaned,
            topK=max(limit * 5, 50),
            withWeight=True,
            allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "v", "eng"),
        )

        results: list[dict[str, Any]] = []
        seen_terms: set[str] = set()
        for term, weight in raw_keywords:
            normalized_term = term.strip()
            if normalized_term in seen_terms:
                continue
            if not self._is_valid_candidate_term(normalized_term):
                continue

            seen_terms.add(normalized_term)
            results.append(
                {
                    "term": normalized_term,
                    "weight": round(float(weight), 4),
                }
            )
            if len(results) >= limit:
                break

        return results

    def extract_core_topics(self, text: str, top_k: int | None = None) -> list[dict[str, Any]]:
        cleaned = self.cleaner.clean_text(text)
        if not cleaned:
            return []

        self._ensure_jieba_ready()
        limit = top_k or self.config.textrank_top_k
        raw_topics = self._jieba_analyse.textrank(
            cleaned,
            topK=max(limit * 3, 15),
            withWeight=True,
            allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "v", "eng"),
        )

        topics: list[dict[str, Any]] = []
        seen_topics: set[str] = set()
        for topic, weight in raw_topics:
            normalized_topic = topic.strip()
            if normalized_topic in seen_topics:
                continue
            if not self._is_valid_candidate_term(normalized_topic):
                continue

            seen_topics.add(normalized_topic)
            topics.append(
                {
                    "topic": normalized_topic,
                    "weight": round(float(weight), 4),
                }
            )
            if len(topics) >= limit:
                break

        return topics

    def compare_wording_evolution(
        self,
        old_report: PreparedText | str,
        new_report: PreparedText | str,
        max_pairs: int = 20,
    ) -> dict[str, Any]:
        old_prepared = self._coerce_prepared_text(old_report)
        new_prepared = self._coerce_prepared_text(new_report)

        old_sentences = self._filter_comparable_sentences(old_prepared.sentences)
        new_sentences = self._filter_comparable_sentences(new_prepared.sentences)
        if not old_sentences or not new_sentences:
            return {
                "matched_pairs": [],
                "average_intensity": 0.0,
                "count": 0,
            }

        model = self._load_embedding_model()
        old_embeddings = model.encode(
            old_sentences,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        new_embeddings = model.encode(
            new_sentences,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        similarity_matrix = old_embeddings @ new_embeddings.T
        lower = self.config.sentence_similarity_lower
        upper = self.config.sentence_similarity_upper

        candidates: list[tuple[float, int, int]] = []
        for old_index, row in enumerate(similarity_matrix):
            for new_index, score in enumerate(row):
                similarity = float(score)
                if similarity < lower or similarity >= upper:
                    continue
                if old_sentences[old_index] == new_sentences[new_index]:
                    continue
                candidates.append((similarity, old_index, new_index))

        candidates.sort(key=lambda item: item[0], reverse=True)

        matched_pairs: list[dict[str, Any]] = []
        used_old: set[int] = set()
        used_new: set[int] = set()
        for similarity, old_index, new_index in candidates:
            if old_index in used_old or new_index in used_new:
                continue

            used_old.add(old_index)
            used_new.add(new_index)
            intensity = self._calculate_evolution_intensity(similarity)
            matched_pairs.append(
                {
                    "old_sentence": old_sentences[old_index],
                    "new_sentence": new_sentences[new_index],
                    "similarity": round(similarity, 4),
                    "evolution_intensity": round(intensity * 100, 2),
                    "strength_label": self._label_evolution_intensity(intensity),
                }
            )
            if len(matched_pairs) >= max_pairs:
                break

        average_intensity = (
            round(mean(pair["evolution_intensity"] for pair in matched_pairs), 2)
            if matched_pairs
            else 0.0
        )
        return {
            "matched_pairs": matched_pairs,
            "average_intensity": average_intensity,
            "count": len(matched_pairs),
        }

    def monitor_topic_attenuation(
        self,
        old_report: PreparedText | str,
        new_report: PreparedText | str,
    ) -> dict[str, Any]:
        old_prepared = self._coerce_prepared_text(old_report)
        new_prepared = self._coerce_prepared_text(new_report)

        old_topics = self.extract_core_topics(
            old_prepared.cleaned_text,
            top_k=self.config.textrank_top_k,
        )
        new_topics = self.extract_core_topics(
            new_prepared.cleaned_text,
            top_k=self.config.textrank_top_k,
        )
        if not old_topics and not new_topics:
            return {
                "core_topics_old": [],
                "core_topics_new": [],
                "changes": [],
                "added_topics": [],
                "retained_topics": [],
                "strengthened_topics": [],
                "removed_count": 0,
                "weakened_count": 0,
                "strengthened_count": 0,
            }

        old_token_count = max(self._estimate_token_count(old_prepared.cleaned_text), 1)
        new_token_count = max(self._estimate_token_count(new_prepared.cleaned_text), 1)

        old_topic_names = {item["topic"] for item in old_topics}
        changes: list[dict[str, Any]] = []
        added_topics: list[dict[str, Any]] = []
        retained_topics: list[dict[str, Any]] = []
        strengthened_topics: list[dict[str, Any]] = []
        removed_count = 0
        weakened_count = 0
        strengthened_count = 0

        for topic in old_topics:
            keyword = topic["topic"]
            old_density = self._calculate_term_density(
                old_prepared.cleaned_text,
                keyword,
                old_token_count,
            )
            new_density = self._calculate_term_density(
                new_prepared.cleaned_text,
                keyword,
                new_token_count,
            )

            if old_density <= 0:
                continue

            decay_ratio = max(0.0, 1.0 - (new_density / old_density))
            amplification_ratio = max(0.0, (new_density / old_density) - 1.0)
            status = "保留"
            if new_density == 0:
                status = "彻底删减"
                removed_count += 1
            elif decay_ratio >= self.config.weakening_ratio_threshold:
                status = "明显弱化"
                weakened_count += 1
            elif new_density > old_density * 1.2:
                status = "明显强化"
                strengthened_count += 1

            item = {
                "topic": keyword,
                "textrank_weight": topic["weight"],
                "old_density": round(old_density, 6),
                "new_density": round(new_density, 6),
                "decay_ratio": round(decay_ratio * 100, 2),
                "amplification_ratio": round(amplification_ratio * 100, 2),
                "status": status,
            }
            changes.append(item)

            if status in {"保留", "明显强化"} and new_density > 0:
                retained_topics.append(item)
            if status == "明显强化":
                strengthened_topics.append(item)

        for topic in new_topics:
            keyword = topic["topic"]
            if keyword in old_topic_names:
                continue

            old_density = self._calculate_term_density(
                old_prepared.cleaned_text,
                keyword,
                old_token_count,
            )
            new_density = self._calculate_term_density(
                new_prepared.cleaned_text,
                keyword,
                new_token_count,
            )
            if new_density <= 0:
                continue

            added_topics.append(
                {
                    "topic": keyword,
                    "new_weight": topic["weight"],
                    "old_density": round(old_density, 6),
                    "new_density": round(new_density, 6),
                    "delta_density": round(max(0.0, new_density - old_density), 6),
                    "status": "新增议题",
                }
            )

        changes.sort(key=lambda item: item["decay_ratio"], reverse=True)
        added_topics.sort(
            key=lambda item: (item["delta_density"], item["new_weight"]),
            reverse=True,
        )
        retained_topics.sort(
            key=lambda item: (item["new_density"], item["textrank_weight"]),
            reverse=True,
        )
        strengthened_topics.sort(
            key=lambda item: (item["amplification_ratio"], item["new_density"]),
            reverse=True,
        )

        return {
            "core_topics_old": old_topics,
            "core_topics_new": new_topics,
            "changes": changes,
            "added_topics": added_topics,
            "retained_topics": retained_topics,
            "strengthened_topics": strengthened_topics,
            "removed_count": removed_count,
            "weakened_count": weakened_count,
            "strengthened_count": strengthened_count,
        }

    def analyze_text_structure(self, prepared: PreparedText) -> dict[str, Any]:
        if not prepared.paragraphs:
            return {
                "paragraph_lengths": [],
                "sentence_lengths": [],
                "avg_paragraph_length": 0,
                "avg_sentence_length": 0,
                "longest_paragraph_length": 0,
                "longest_sentence_length": 0,
            }

        paragraph_lengths = [len(p) for p in prepared.paragraphs]
        sentence_lengths = [len(s) for s in prepared.sentences]

        return {
            "paragraph_lengths": paragraph_lengths,
            "sentence_lengths": sentence_lengths,
            "avg_paragraph_length": sum(paragraph_lengths) / len(paragraph_lengths) if paragraph_lengths else 0,
            "avg_sentence_length": sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0,
            "longest_paragraph_length": max(paragraph_lengths) if paragraph_lengths else 0,
            "longest_sentence_length": max(sentence_lengths) if sentence_lengths else 0,
        }

    def _ensure_jieba_ready(self) -> None:
        if self._jieba is not None and self._jieba_analyse is not None:
            return

        try:
            import jieba
            import jieba.analyse
        except ImportError as exc:
            raise RuntimeError("缺少 jieba 依赖，请先安装 jieba。") from exc

        self._jieba = jieba
        self._jieba_analyse = jieba.analyse

        user_dict_path = self.config.resolved_custom_dictionary_path
        if os.path.exists(user_dict_path):
            try:
                self._jieba.load_userdict(user_dict_path)
            except Exception:
                pass

    def _load_embedding_model(self):
        if self._embedding_model is not None:
            return self._embedding_model

        initialize_runtime_environment(self.config)

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "缺少 sentence-transformers 依赖，请先安装 sentence-transformers。"
            ) from exc

        self._embedding_model = SentenceTransformer(
            self.config.resolved_model_dir,
            device="cpu",
            local_files_only=self.config.local_files_only,
            cache_folder=None,
        )

        try:
            self._embedding_model.encode(["预热模型"], show_progress_bar=False)
        except Exception:
            pass

        return self._embedding_model

    def _split_sentences_from_cleaned(self, cleaned_text: str) -> list[str]:
        if not cleaned_text:
            return []
        chunks = re.split(r"(?<=[。！？；;!?])", cleaned_text)
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def _coerce_prepared_text(self, value: PreparedText | str) -> PreparedText:
        if isinstance(value, PreparedText):
            return value
        return self.prepare_text(value)

    def _filter_comparable_sentences(self, sentences: list[str]) -> list[str]:
        filtered: list[str] = []
        for sentence in sentences:
            normalized = sentence.strip()
            if len(normalized) < 8:
                continue
            if re.fullmatch(r"[0-9一二三四五六七八九十百零两年月日、，。；：:（）()\-\s]+", normalized):
                continue
            filtered.append(normalized)
        return filtered

    def _estimate_token_count(self, text: str) -> int:
        self._ensure_jieba_ready()
        tokens = [token.strip() for token in self._jieba.lcut(text) if token.strip()]
        return len(tokens)

    def _calculate_term_density(self, text: str, term: str, token_count: int) -> float:
        if not text or not term or token_count <= 0:
            return 0.0
        occurrences = len(re.findall(re.escape(term), text))
        return occurrences / token_count

    def _is_valid_candidate_term(self, term: str) -> bool:
        if len(term) < 2:
            return False
        if term in self._blocked_terms:
            return False
        if re.fullmatch(r"[0-9A-Za-z\W_]+", term):
            return False
        return True

    def _calculate_evolution_intensity(self, similarity: float) -> float:
        lower = self.config.sentence_similarity_lower
        upper = self.config.sentence_similarity_upper
        if upper <= lower:
            return 0.0
        normalized = (upper - similarity) / (upper - lower)
        return max(0.0, min(1.0, normalized))

    @staticmethod
    def _label_evolution_intensity(intensity: float) -> str:
        if intensity >= 0.67:
            return "高"
        if intensity >= 0.34:
            return "中"
        return "低"
