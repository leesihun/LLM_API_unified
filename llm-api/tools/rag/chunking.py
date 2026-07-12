"""
Chunking strategies for RAG.

Strategies (config.RAG_CHUNKING_STRATEGY):
- fixed:     character windows with overlap (baseline)
- sentence:  sentence-aware, never cuts mid-sentence
- semantic:  sentence groups split where embedding similarity drops
- recursive: paragraph/structure-aware
"""
import re
from typing import List, Literal

import numpy as np

# Sentence boundary: half-width .!? and full-width Korean/CJK 。！？
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?。！？])\s+')

Strategy = Literal["fixed", "semantic", "recursive", "sentence"]


class Chunker:
    """Splits text into chunks using the configured strategy.

    Semantic chunking needs an embedding model; without one it degrades to
    sentence-aware chunking.
    """

    def __init__(self, embedding_model=None, chunk_size: int = 512, overlap: int = 50):
        self.embedding_model = embedding_model
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, strategy: Strategy = "semantic") -> List[str]:
        if strategy == "fixed":
            return self._fixed(text)
        if strategy == "semantic":
            return self._semantic(text)
        if strategy == "recursive":
            return self._recursive(text)
        if strategy == "sentence":
            return self._sentence_aware(text)
        raise ValueError(f"Unknown chunking strategy: {strategy}")

    def _fixed(self, text: str) -> List[str]:
        chunks = []
        start = 0
        while start < len(text):
            chunk = text[start:start + self.chunk_size]
            if chunk:
                chunks.append(chunk)
            start += self.chunk_size - self.overlap
        return chunks

    def _sentence_aware(self, text: str) -> List[str]:
        sentences = _SENTENCE_SPLIT.split(text)

        chunks = []
        current: List[str] = []
        current_size = 0
        for sentence in sentences:
            if current_size + len(sentence) > self.chunk_size and current:
                chunks.append(' '.join(current))
                # Carry the last sentence over as overlap
                current = [current[-1]] if self.overlap > 0 else []
                current_size = sum(len(s) for s in current)
            current.append(sentence)
            current_size += len(sentence)

        if current:
            chunks.append(' '.join(current))
        return chunks

    def _semantic(self, text: str) -> List[str]:
        """Group sentences, breaking where consecutive-sentence similarity drops
        into the bottom quartile or the chunk would exceed chunk_size."""
        if self.embedding_model is None:
            return self._sentence_aware(text)

        sentences = _SENTENCE_SPLIT.split(text)
        if len(sentences) <= 1:
            return [text]

        embeddings = self.embedding_model.encode(sentences)
        norms = np.linalg.norm(embeddings, axis=1)
        # Cosine similarity of each sentence with the next, vectorized
        similarities = np.sum(embeddings[:-1] * embeddings[1:], axis=1) / (norms[:-1] * norms[1:])
        threshold = np.percentile(similarities, 25)

        chunks = []
        current = [sentences[0]]
        current_size = len(sentences[0])
        for i, sentence in enumerate(sentences[1:]):
            should_break = similarities[i] < threshold or current_size + len(sentence) > self.chunk_size
            if should_break and current:
                chunks.append(' '.join(current))
                # Carry the last 1-2 sentences over as overlap
                current = current[-2:] if len(current) >= 2 else current[-1:]
                current = current + [sentence]
                current_size = sum(len(s) for s in current)
            else:
                current.append(sentence)
                current_size += len(sentence)

        if current:
            chunks.append(' '.join(current))
        return chunks

    def _recursive(self, text: str) -> List[str]:
        """Paragraph-first; oversized paragraphs fall back to sentence chunking."""
        chunks = []
        current: List[str] = []
        current_size = 0
        for para in text.split('\n\n'):
            para = para.strip()
            if not para:
                continue

            if len(para) > self.chunk_size:
                if current:
                    chunks.append('\n\n'.join(current))
                    current = []
                    current_size = 0
                chunks.extend(self._sentence_aware(para))
            elif current_size + len(para) > self.chunk_size and current:
                chunks.append('\n\n'.join(current))
                current = [para]
                current_size = len(para)
            else:
                current.append(para)
                current_size += len(para) + 2  # +2 for \n\n

        if current:
            chunks.append('\n\n'.join(current))
        return chunks
