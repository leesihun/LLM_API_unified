"""
Hybrid Retrieval: Combines dense (semantic) and sparse (keyword) search
using Reciprocal Rank Fusion (RRF) for maximum RAG accuracy
"""
import numpy as np
from typing import List, Dict, Any, Tuple
from rank_bm25 import BM25Okapi
import re

# Standard RRF constant (from the original RRF paper)
RRF_K = 60


class HybridRetriever:
    """
    Combines dense semantic search (FAISS) with sparse keyword search (BM25)
    using Reciprocal Rank Fusion (RRF).

    RRF is more robust than raw score interpolation because it operates on
    ranks rather than scores, avoiding issues with different score distributions.
    """

    def __init__(self, alpha: float = 0.5):
        """
        Initialize hybrid retriever

        Args:
            alpha: Weight for dense vs sparse RRF contributions
                   (0.0 = pure sparse, 1.0 = pure dense, 0.5 = balanced)
        """
        self.alpha = alpha
        self.bm25 = None
        self.tokenized_corpus = None

    def index_corpus(self, documents: List[str]):
        """
        Index corpus for BM25 sparse retrieval

        Args:
            documents: List of document chunks
        """
        self.tokenized_corpus = [self._tokenize(doc) for doc in documents]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25"""
        tokens = re.findall(r'\w+', text.lower())
        return tokens

    def search(
        self,
        query: str,
        dense_indices: np.ndarray,
        k: int = 5
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Perform hybrid search using Reciprocal Rank Fusion.

        Takes ranked indices from FAISS (dense retriever) and computes BM25
        ranks independently, then fuses using RRF over their union.

        Args:
            query: Search query
            dense_indices: Ranked indices from FAISS dense search (best first)
            k: Number of results to return

        Returns:
            Tuple of (rrf_scores, indices) sorted by RRF score descending
        """
        if self.bm25 is None:
            raise ValueError("Must call index_corpus() before search()")

        # Get BM25 scores and derive sparse ranking
        query_tokens = self._tokenize(query)
        sparse_scores = self.bm25.get_scores(query_tokens)
        sparse_ranked = np.argsort(sparse_scores)[::-1][:len(dense_indices)]

        # Build rank maps: index -> rank (0-based)
        dense_rank_map = {int(idx): rank for rank, idx in enumerate(dense_indices)}
        sparse_rank_map = {int(idx): rank for rank, idx in enumerate(sparse_ranked)}

        # Union of candidates from both retrievers
        candidates = set(dense_rank_map.keys()) | set(sparse_rank_map.keys())

        # Compute RRF score for each candidate
        rrf_scores = {}
        for idx in candidates:
            dense_rrf = 0.0
            sparse_rrf = 0.0

            if idx in dense_rank_map:
                dense_rrf = 1.0 / (RRF_K + dense_rank_map[idx] + 1)
            if idx in sparse_rank_map:
                sparse_rrf = 1.0 / (RRF_K + sparse_rank_map[idx] + 1)

            rrf_scores[idx] = self.alpha * dense_rrf + (1 - self.alpha) * sparse_rrf

        # Sort by RRF score descending and take top-k
        sorted_candidates = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:k]

        top_indices = np.array([idx for idx, _ in sorted_candidates])
        top_scores = np.array([score for _, score in sorted_candidates])

        return top_scores, top_indices


class RerankerCrossEncoder:
    """
    Two-stage retrieval: Initial retrieval + reranking with cross-encoder

    This can improve accuracy by 15-20% compared to single-stage retrieval.
    Uses a multilingual cross-encoder to support Korean + English queries and documents.
    """

    def __init__(self, model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"):
        """
        Initialize reranker

        Args:
            model_name: Cross-encoder model for reranking (must support target languages)
        """
        self.model_name = model_name
        self.model = None

    def _load_model(self):
        """Lazy load cross-encoder model"""
        if self.model is None:
            try:
                from sentence_transformers import CrossEncoder
                self.model = CrossEncoder(self.model_name)
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )

    @staticmethod
    def _sigmoid(x: float) -> float:
        """
        Apply sigmoid normalization to cross-encoder logits.

        Cross-encoder models return raw logits (typically -10 to +10 range).
        Sigmoid maps these to probability-like scores (0 to 1):
        - Negative logits → 0.0 to 0.5 (less relevant)
        - Zero logit → 0.5 (neutral)
        - Positive logits → 0.5 to 1.0 (more relevant)

        Args:
            x: Raw cross-encoder logit score

        Returns:
            Normalized score in range (0, 1)

        Examples:
            -10.0 → 0.000 (very irrelevant)
            -1.767 → 0.146 (somewhat irrelevant)
            0.0 → 0.500 (neutral)
            3.0 → 0.953 (highly relevant)
            10.0 → 1.000 (extremely relevant)
        """
        import numpy as np
        return float(1.0 / (1.0 + np.exp(-x)))

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Rerank documents using cross-encoder

        Args:
            query: Search query
            documents: List of retrieved documents with 'chunk' field
            top_k: Number of top documents to return

        Returns:
            Reranked documents with updated scores
        """
        self._load_model()

        if len(documents) == 0:
            return documents

        # Prepare query-document pairs
        pairs = [[query, doc['chunk']] for doc in documents]

        # Get cross-encoder scores
        scores = self.model.predict(pairs)

        # Update document scores with sigmoid normalization
        for doc, score in zip(documents, scores):
            doc['rerank_score_raw'] = float(score)  # Raw cross-encoder logit
            doc['rerank_score'] = self._sigmoid(score)  # Normalized to 0-1 range
            doc['original_score'] = doc.get('score', 0.0)  # Original FAISS/RRF score

        # Sort by rerank score
        reranked = sorted(documents, key=lambda x: x['rerank_score'], reverse=True)

        return reranked[:top_k]
