"""
Retrieval quality stages, both optional and config-gated:

- HybridRetriever: fuses dense (FAISS) and sparse (BM25) rankings with
  Reciprocal Rank Fusion (RRF). Rank-based fusion is robust to the score
  distributions of the two retrievers.
- RerankerCrossEncoder: second-stage cross-encoder reranking of candidates.
"""
import re
from typing import Any, Dict, List, Tuple

import numpy as np
from rank_bm25 import BM25Okapi

# Standard RRF constant (from the original RRF paper)
RRF_K = 60


def tokenize(text: str) -> List[str]:
    """Simple word tokenization for BM25 (shared with index build)."""
    return re.findall(r'\w+', text.lower())


class HybridRetriever:
    """Fuses FAISS dense ranking with BM25 sparse ranking via RRF."""

    def __init__(self, alpha: float = 0.5):
        """alpha weights dense vs sparse RRF contributions
        (0.0 = pure sparse, 1.0 = pure dense)."""
        self.alpha = alpha
        self.bm25 = None
        self.tokenized_corpus = None

    def index_corpus(self, documents: List[str]):
        self.tokenized_corpus = [tokenize(doc) for doc in documents]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def search(
        self,
        query: str,
        dense_indices: np.ndarray,
        k: int = 5,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return (rrf_scores, indices) for the top-k RRF-fused candidates.

        dense_indices must be the FAISS result ranking, best first.
        """
        if self.bm25 is None:
            raise ValueError("Must call index_corpus() before search()")

        sparse_scores = self.bm25.get_scores(tokenize(query))
        sparse_ranked = np.argsort(sparse_scores)[::-1][:len(dense_indices)]

        dense_rank = {int(idx): rank for rank, idx in enumerate(dense_indices)}
        sparse_rank = {int(idx): rank for rank, idx in enumerate(sparse_ranked)}

        rrf_scores = {}
        for idx in dense_rank.keys() | sparse_rank.keys():
            dense_rrf = 1.0 / (RRF_K + dense_rank[idx] + 1) if idx in dense_rank else 0.0
            sparse_rrf = 1.0 / (RRF_K + sparse_rank[idx] + 1) if idx in sparse_rank else 0.0
            rrf_scores[idx] = self.alpha * dense_rrf + (1 - self.alpha) * sparse_rrf

        top = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:k]
        return np.array([score for _, score in top]), np.array([idx for idx, _ in top])


class RerankerCrossEncoder:
    """Cross-encoder reranking of first-stage candidates (lazy-loaded model)."""

    def __init__(self, model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"):
        self.model_name = model_name
        self.model = None

    def _load_model(self):
        if self.model is None:
            from sentence_transformers import CrossEncoder
            import config
            self.model = CrossEncoder(self.model_name, device=config.RAG_EMBEDDING_DEVICE)

    def cleanup(self):
        """Release model from GPU/CPU memory."""
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except ImportError:
            has_cuda = False

        if self.model is not None:
            if has_cuda:
                try:
                    self.model.model.cpu()
                except Exception:
                    pass
            del self.model
            self.model = None

        if has_cuda:
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Rerank documents (each with a 'chunk' field) by cross-encoder score.

        Adds rerank_score (sigmoid-normalized to 0-1), rerank_score_raw
        (the logit), and original_score to each document.
        """
        if not documents:
            return documents

        self._load_model()
        scores = self.model.predict([[query, doc['chunk']] for doc in documents])

        for doc, score in zip(documents, scores):
            doc['rerank_score_raw'] = float(score)
            doc['rerank_score'] = float(1.0 / (1.0 + np.exp(-score)))
            doc['original_score'] = doc.get('score', 0.0)

        return sorted(documents, key=lambda x: x['rerank_score'], reverse=True)[:top_k]
