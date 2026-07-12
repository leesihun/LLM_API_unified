"""
RAG tool: per-user FAISS collections with document upload and retrieval.

One RAGTool class covers the whole pipeline; the optional quality stages are
config-gated at runtime:
- chunking strategy    config.RAG_CHUNKING_STRATEGY (fixed/sentence/semantic/recursive)
- hybrid search (BM25) config.RAG_USE_HYBRID_SEARCH
- reranking            config.RAG_USE_RERANKING
"""
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

import config
from backend.utils.prompts_log_append import log_to_prompts_file
from tools.rag import readers
from tools.rag.chunking import Chunker

# ---------------------------------------------------------------------------
# Process-level singletons — loaded once, reused across all requests.
# The embedding model is the SINGLE source of truth in this worker; never
# instantiate SentenceTransformer anywhere else — each duplicate stacks
# another ~2.3 GB of VRAM.
# ---------------------------------------------------------------------------
_GLOBAL_EMBEDDING_MODEL = None            # SentenceTransformer (GPU-resident)
_GLOBAL_CHUNKER: Optional[Chunker] = None
_GLOBAL_RERANKER = None                   # RerankerCrossEncoder (GPU-resident)
_GLOBAL_FAISS_CACHE: Dict[str, Any] = {}  # "path:mtime" -> faiss.Index
_GLOBAL_BM25_CACHE: Dict[str, Any] = {}   # "path:mtime" -> BM25Okapi


def get_global_embedding_model():
    """Load-or-return the shared SentenceTransformer singleton for this process."""
    global _GLOBAL_EMBEDDING_MODEL
    if _GLOBAL_EMBEDDING_MODEL is not None:
        return _GLOBAL_EMBEDDING_MODEL

    from sentence_transformers import SentenceTransformer

    # Load in FP16 to halve model-weight VRAM (~2.3 GB -> ~1.15 GB for bge-m3);
    # accuracy impact on bge-m3 is near-zero in practice.
    model_kwargs = {}
    if config.RAG_EMBEDDING_DEVICE == "cuda":
        try:
            import torch
            model_kwargs["torch_dtype"] = torch.float16
        except ImportError:
            pass

    print(f"[RAG] Loading embedding model: {config.RAG_EMBEDDING_MODEL}")
    _GLOBAL_EMBEDDING_MODEL = SentenceTransformer(
        config.RAG_EMBEDDING_MODEL,
        device=config.RAG_EMBEDDING_DEVICE,
        model_kwargs=model_kwargs,
    )
    dim = _GLOBAL_EMBEDDING_MODEL.get_sentence_embedding_dimension()
    print(f"[RAG] Embedding model loaded - dimension: {dim}")
    return _GLOBAL_EMBEDDING_MODEL


def _release_cuda_cache(context: str = ""):
    """Return freed CUDA blocks to the driver so nvidia-smi drops back down.

    Costs one cudaStreamSynchronize (~10-30 ms) — fine in upload paths,
    conditional on the retrieve hot path (see _maybe_release_cuda_cache).
    """
    try:
        import torch
        if torch.cuda.is_available():
            before = torch.cuda.memory_reserved() / (1024 ** 3)
            torch.cuda.empty_cache()
            after = torch.cuda.memory_reserved() / (1024 ** 3)
            if before - after > 0.01:
                print(f"[RAG] CUDA cache released ({context}): "
                      f"reserved {before:.2f} -> {after:.2f} GiB")
    except ImportError:
        pass


def _maybe_release_cuda_cache(threshold_gib: float = 4.0):
    """Release CUDA cache only when fragmentation (reserved - allocated)
    exceeds threshold_gib, keeping the retrieve hot path fast."""
    try:
        import torch
        if torch.cuda.is_available():
            frag = (torch.cuda.memory_reserved() - torch.cuda.memory_allocated()) / (1024 ** 3)
            if frag > threshold_gib:
                _release_cuda_cache(f"fragmentation {frag:.1f} GiB")
    except ImportError:
        pass


def _vram_mb() -> Optional[float]:
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / (1024 ** 2)
    except ImportError:
        pass
    return None


def _reset_peak_vram():
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except ImportError:
        pass


def _peak_vram_mb() -> Optional[float]:
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / (1024 ** 2)
    except ImportError:
        pass
    return None


# ---------------------------------------------------------------------------
# Chunk-lookup helpers: metadata["chunk_lookup"] maps global FAISS index ->
# {doc_id, chunk_index} so retrieve() resolves hits without scanning documents.
# ---------------------------------------------------------------------------

def _ensure_chunk_lookup(metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup = metadata.get("chunk_lookup")
    if isinstance(lookup, dict):
        return lookup
    metadata["chunk_lookup"] = {}
    return metadata["chunk_lookup"]


def _set_chunk_lookup_for_doc(metadata: Dict[str, Any], doc_id: str, chunk_indices: List[int]):
    lookup = _ensure_chunk_lookup(metadata)
    for local_idx, global_idx in enumerate(chunk_indices):
        lookup[str(global_idx)] = {"doc_id": doc_id, "chunk_index": local_idx}


def _rebuild_chunk_lookup(metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for doc_id, doc_meta in metadata.get("documents", {}).items():
        for local_idx, global_idx in enumerate(doc_meta.get("chunk_indices", [])):
            lookup[str(global_idx)] = {"doc_id": doc_id, "chunk_index": local_idx}
    metadata["chunk_lookup"] = lookup
    return lookup


def _new_metadata(collection_name: str) -> Dict[str, Any]:
    return {
        "collection_name": collection_name,
        "created_at": time.time(),
        "documents": {},
        "chunk_count": 0,
        "chunk_lookup": {},
    }


class RAGTool:
    """Per-user RAG collections backed by FAISS + JSON metadata on disk."""

    def __init__(self, username: str):
        self.username = username
        self.user_docs_dir = config.RAG_DOCUMENTS_DIR / username
        self.user_index_dir = config.RAG_INDEX_DIR / username
        self.user_metadata_dir = config.RAG_METADATA_DIR / username

        for d in (self.user_docs_dir, self.user_index_dir, self.user_metadata_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.embedding_model = None  # lazy — bound to the process singleton
        self.embedding_dim = None
        self.chunker: Optional[Chunker] = None
        self.hybrid_retriever = None
        self.reranker = None

    # ------------------------------------------------------------------
    # Lazy component loading (all process-level singletons)
    # ------------------------------------------------------------------

    def _load_embedding_model(self):
        global _GLOBAL_CHUNKER
        self.embedding_model = get_global_embedding_model()
        self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()
        if _GLOBAL_CHUNKER is None:
            _GLOBAL_CHUNKER = Chunker(
                embedding_model=self.embedding_model,
                chunk_size=config.RAG_CHUNK_SIZE,
                overlap=config.RAG_CHUNK_OVERLAP,
            )
        self.chunker = _GLOBAL_CHUNKER

    def _load_hybrid_retriever(self):
        if self.hybrid_retriever is None and config.RAG_USE_HYBRID_SEARCH:
            from tools.rag.retrieval import HybridRetriever
            self.hybrid_retriever = HybridRetriever(alpha=config.RAG_HYBRID_ALPHA)

    def _load_reranker(self):
        global _GLOBAL_RERANKER
        if not config.RAG_USE_RERANKING:
            return
        if _GLOBAL_RERANKER is None:
            from tools.rag.retrieval import RerankerCrossEncoder
            _GLOBAL_RERANKER = RerankerCrossEncoder(model_name=config.RAG_RERANKER_MODEL)
            print(f"[RAG] Reranker loaded: {config.RAG_RERANKER_MODEL}")
        self.reranker = _GLOBAL_RERANKER

    def cleanup(self):
        """Clear instance references. Global singletons are kept alive
        intentionally so the next request reuses them without reloading."""
        self.embedding_model = None
        self.chunker = None
        self.reranker = None
        if self.hybrid_retriever is not None:
            self.hybrid_retriever.bm25 = None
            self.hybrid_retriever.tokenized_corpus = None
            self.hybrid_retriever = None

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def create_collection(self, collection_name: str) -> Dict[str, Any]:
        collection_dir = self.user_docs_dir / collection_name
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"

        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                return {
                    "success": False,
                    "error": f"Collection '{collection_name}' already exists "
                             f"with {len(existing.get('documents', {}))} documents",
                }
            except Exception:
                print(f"[RAG] Corrupted metadata for '{collection_name}', recreating...")

        collection_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(_new_metadata(collection_name), f, indent=2)
        except Exception as e:
            return {"success": False, "error": f"Failed to create metadata file: {e}"}

        return {"success": True, "collection_name": collection_name, "path": str(collection_dir)}

    def list_collections(self) -> Dict[str, Any]:
        collections = []
        for metadata_file in self.user_metadata_dir.glob("*.json"):
            # BM25 sidecars live in the index dir, but guard against strays
            if metadata_file.name.endswith("_bm25.json"):
                continue
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                collections.append({
                    "name": metadata["collection_name"],
                    "documents": len(metadata["documents"]),
                    "chunks": metadata["chunk_count"],
                    "created_at": metadata["created_at"],
                })
            except Exception:
                continue
        return {"success": True, "collections": collections}

    def delete_collection(self, collection_name: str) -> Dict[str, Any]:
        import shutil

        metadata_path = self.user_metadata_dir / f"{collection_name}.json"
        if not metadata_path.exists():
            return {"success": False, "error": f"Collection '{collection_name}' does not exist"}

        collection_dir = self.user_docs_dir / collection_name
        if collection_dir.exists():
            shutil.rmtree(collection_dir)
        for p in (
            self.user_index_dir / f"{collection_name}.index",
            self.user_index_dir / f"{collection_name}_bm25.json",
            metadata_path,
        ):
            if p.exists():
                p.unlink()

        return {"success": True, "collection_name": collection_name}

    def list_documents(self, collection_name: str) -> Dict[str, Any]:
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"
        if not metadata_path.exists():
            return {"success": False, "error": f"Collection '{collection_name}' does not exist"}

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            documents = []
            for doc_id, doc_meta in metadata.get("documents", {}).items():
                chunk_count = len(self._get_document_chunks(doc_meta)) or len(doc_meta.get("chunk_indices", []))
                documents.append({
                    "id": doc_id,
                    "name": doc_meta["name"],
                    "path": doc_meta["path"],
                    "chunks": chunk_count,
                    "uploaded_at": doc_meta["uploaded_at"],
                })

            return {
                "success": True,
                "collection_name": collection_name,
                "documents": documents,
                "total_documents": len(documents),
                "total_chunks": metadata.get("chunk_count", 0),
            }
        except Exception as e:
            return {"success": False, "error": f"Error listing documents: {e}"}

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_document(
        self,
        collection_name: str,
        document_path: str,
        document_content: Optional[str] = None,
        document_name: Optional[str] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> Dict[str, Any]:
        """Read, chunk, embed, and index one document into a collection.

        The collection is created on the fly if it doesn't exist yet.
        progress_callback(message, pct) is invoked at stage boundaries.
        """
        def progress(msg: str, pct: float):
            if progress_callback:
                progress_callback(msg, pct)

        vram_before = _vram_mb()
        _reset_peak_vram()
        self._load_embedding_model()

        collection_dir = self.user_docs_dir / collection_name
        collection_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"

        metadata = _new_metadata(collection_name)
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            except Exception as e:
                print(f"[RAG] Failed to load metadata, creating new: {e}")
        _ensure_chunk_lookup(metadata)

        # Read
        progress("Reading document", 5)
        if document_content is None:
            doc_path = Path(document_path)
            if not doc_path.exists():
                return {"success": False, "error": "Document file not found"}
            if doc_path.suffix not in config.RAG_SUPPORTED_FORMATS:
                return {"success": False, "error": f"Unsupported format: {doc_path.suffix}"}
            # Scale PDF page-extraction progress into the 5-35% band
            document_content = readers.read_document(
                doc_path,
                progress_callback=lambda m, p: progress(m, 5 + p * 0.3),
            )
            doc_name = document_name or doc_path.name
        else:
            doc_name = document_name or Path(document_path).name

        print(f"[RAG] Uploading '{doc_name}' to '{collection_name}' "
              f"({len(document_content)} chars)")

        # Chunk
        progress("Chunking document", 40)
        chunk_start = time.time()
        chunks = self.chunker.chunk(document_content, strategy=config.RAG_CHUNKING_STRATEGY)
        chunk_time = time.time() - chunk_start
        print(f"[RAG] {len(chunks)} chunks ({config.RAG_CHUNKING_STRATEGY}, {chunk_time:.1f}s)")

        # Embed (normalized for cosine similarity with IndexFlatIP)
        progress(f"Embedding {len(chunks)} chunks", 50)
        embed_start = time.time()
        embeddings = self.embedding_model.encode(
            chunks,
            batch_size=config.RAG_EMBEDDING_BATCH_SIZE,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        embed_time = time.time() - embed_start
        print(f"[RAG] Embeddings generated ({embed_time:.1f}s)")

        # Index
        progress("Updating index", 85)
        index = self._load_or_create_index(collection_name, self.embedding_dim)
        start_idx = index.ntotal
        index.add(np.array(embeddings).astype('float32'))
        vram_peak = _peak_vram_mb()
        vram_after = _vram_mb()

        # Metadata (timestamp in the id hash avoids collision on re-upload)
        upload_time = time.time()
        doc_id = hashlib.md5(f"{doc_name}:{upload_time}".encode()).hexdigest()
        chunk_indices = list(range(start_idx, index.ntotal))
        metadata["documents"][doc_id] = {
            "name": doc_name,
            "path": str(document_path),
            "chunk_indices": chunk_indices,
            "chunks": chunks,
            "uploaded_at": upload_time,
        }
        metadata["chunk_count"] = index.ntotal
        _set_chunk_lookup_for_doc(metadata, doc_id, chunk_indices)

        # Persist
        progress("Saving index and metadata", 92)
        try:
            self._save_index(index, collection_name)
        except Exception as e:
            return {"success": False, "error": f"Failed to save index: {e}"}

        if config.RAG_USE_HYBRID_SEARCH:
            self._rebuild_bm25_index(collection_name, metadata)

        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            return {"success": False, "error": f"Failed to save metadata: {e}"}

        _release_cuda_cache("upload_document")
        progress("Upload complete", 100)

        result = {
            "success": True,
            "document_name": doc_name,
            "chunks_created": len(chunks),
            "total_chunks": index.ntotal,
            "chunking_time": chunk_time,
            "embedding_time": embed_time,
        }
        if vram_before is not None:
            result["vram_before_mb"] = round(vram_before, 1)
            result["vram_after_mb"] = round(vram_after, 1) if vram_after is not None else None
            result["vram_peak_mb"] = round(vram_peak, 1) if vram_peak is not None else None
            result["vram_delta_mb"] = round(vram_after - vram_before, 1) if vram_after is not None else None
        return result

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    def retrieve(
        self,
        collection_name: str,
        query: str,
        max_results: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Retrieve relevant chunks for a query.

        Pipeline (stages 2 and 4 are config-gated):
        1. Dense retrieval (FAISS)
        2. Hybrid RRF fusion with BM25       — RAG_USE_HYBRID_SEARCH
        3. Chunk resolution + context window
        4. Cross-encoder reranking           — RAG_USE_RERANKING
        5. Score-threshold filtering
        """
        _log_lines = [
            "\n\n", "=" * 80, "TOOL EXECUTION: rag", "=" * 80,
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
            "INPUT:", f"  Username: {self.username}",
            f"  Collection: {collection_name}", f"  Query: {query}",
            f"  Max Results: {max_results or 'default'}",
        ]

        def _fail(error: str) -> Dict[str, Any]:
            _log_lines.extend(["", "OUTPUT:", "  Status: ERROR", f"  Error: {error}", "", "=" * 80])
            log_to_prompts_file("\n".join(_log_lines))
            return {"success": False, "error": error}

        start_time = time.time()
        self._load_embedding_model()
        self._load_hybrid_retriever()
        self._load_reranker()

        metadata_path = self.user_metadata_dir / f"{collection_name}.json"
        if not metadata_path.exists():
            return _fail(f"Collection '{collection_name}' does not exist")

        index = self._load_index(collection_name)
        if index is None:
            return _fail(f"No index found for collection '{collection_name}'")

        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        chunk_lookup = metadata.get("chunk_lookup")
        if not isinstance(chunk_lookup, dict) or len(chunk_lookup) != metadata.get("chunk_count", 0):
            chunk_lookup = _rebuild_chunk_lookup(metadata)
            try:
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2)
            except Exception:
                pass

        if index.ntotal == 0:
            return {"success": True, "documents": [], "message": "Collection is empty"}

        # Stage 1: dense retrieval. Retrieve a wider candidate set when a
        # reranker will narrow it afterwards.
        query_embedding = self.embedding_model.encode(
            [config.RAG_QUERY_PREFIX + query],
            normalize_embeddings=True,
        )[0]
        final_k = max_results or config.RAG_MAX_RESULTS
        k = min(config.RAG_RERANKING_TOP_K if config.RAG_USE_RERANKING else final_k, index.ntotal)
        distances, indices = index.search(np.array([query_embedding]).astype('float32'), k)

        # Stage 2: hybrid RRF fusion (dense + BM25)
        hybrid_used = False
        if self.hybrid_retriever is not None:
            bm25 = self._load_bm25(collection_name, metadata)
            if bm25 is not None:
                rrf_scores, top_indices = self.hybrid_retriever.search(
                    query, dense_indices=indices[0], k=k,
                )
                indices = np.array([top_indices])
                # Normalize RRF scores (~0.005-0.016 raw) to 0-1 so the score
                # threshold below still applies.
                max_rrf = rrf_scores.max() if len(rrf_scores) > 0 and rrf_scores.max() > 0 else 1.0
                distances = np.array([rrf_scores / max_rrf])
                hybrid_used = True

        # Stage 3: resolve chunks + context window
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:  # FAISS pads with -1 when k > ntotal
                continue
            ref = chunk_lookup.get(str(int(idx)))
            if not ref:
                continue
            doc_meta = metadata["documents"].get(ref["doc_id"])
            if not doc_meta:
                continue

            doc_chunks = self._get_document_chunks(doc_meta)
            chunk_local_idx = int(ref["chunk_index"])
            if not doc_chunks or chunk_local_idx >= len(doc_chunks):
                continue

            if hybrid_used or config.RAG_SIMILARITY_METRIC == "cosine":
                score = float(dist)  # already similarity / normalized RRF
            else:
                score = float(1 / (1 + dist))  # L2 distance -> similarity

            window = config.RAG_CONTEXT_WINDOW
            start_ctx = max(0, chunk_local_idx - window)
            end_ctx = min(len(doc_chunks), chunk_local_idx + window + 1)
            results.append({
                "document": doc_meta["name"],
                "chunk": "\n---\n".join(doc_chunks[start_ctx:end_ctx]),
                "score": score,
                "chunk_index": chunk_local_idx,
            })

        # Stage 4: reranking (or plain truncation)
        if self.reranker is not None and results:
            results = self.reranker.rerank(query, results, top_k=final_k)
        else:
            results = results[:final_k]

        # Stage 5: score-threshold filter
        score_key = "rerank_score" if any("rerank_score" in r for r in results) else "score"
        results = [r for r in results if r[score_key] >= config.RAG_MIN_SCORE_THRESHOLD]

        total_time = time.time() - start_time
        print(f"[RAG] retrieve('{collection_name}', '{query[:60]}') -> "
              f"{len(results)} results in {total_time:.2f}s "
              f"(hybrid={hybrid_used}, rerank={self.reranker is not None})")

        _log_lines.extend(["", "OUTPUT:", "  Status: SUCCESS",
            f"  Results Found: {len(results)}", f"  Execution Time: {total_time:.2f}s",
            "", "RESULTS:"])
        for i, result in enumerate(results, 1):
            _log_lines.extend(["", f"  Result {i}:", f"    Document: {result['document']}",
                f"    Chunk Index: {result['chunk_index']}",
                f"    Score: {result[score_key]:.3f}",
                f"    Content: {result['chunk'][:200]}..."])
        _log_lines.extend(["", "=" * 80])
        log_to_prompts_file("\n".join(_log_lines))

        _maybe_release_cuda_cache()

        return {
            "success": True,
            "documents": results,
            "query": query,
            "num_results": len(results),
            "execution_time": total_time,
        }

    # ------------------------------------------------------------------
    # Delete document (rebuilds the FAISS + BM25 indexes without it)
    # ------------------------------------------------------------------

    def delete_document(self, collection_name: str, document_id: str) -> Dict[str, Any]:
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"
        if not metadata_path.exists():
            return {"success": False, "error": f"Collection '{collection_name}' does not exist"}

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if document_id not in metadata["documents"]:
                return {"success": False, "error": f"Document '{document_id}' not found in collection"}

            deleted_doc = metadata["documents"].pop(document_id)
            deleted_chunks_count = len(self._get_document_chunks(deleted_doc))
            chunks_file = deleted_doc.get("chunks_file")
            if chunks_file and Path(chunks_file).exists():
                Path(chunks_file).unlink()

            self._load_embedding_model()

            all_chunks = []
            for doc_meta in metadata["documents"].values():
                all_chunks.extend(self._get_document_chunks(doc_meta))

            import faiss
            if all_chunks:
                embeddings = self.embedding_model.encode(
                    all_chunks,
                    batch_size=config.RAG_EMBEDDING_BATCH_SIZE,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                )
                index = self._new_index(self.embedding_dim)
                index.add(np.array(embeddings).astype('float32'))

                current_idx = 0
                for doc_meta in metadata["documents"].values():
                    n = len(self._get_document_chunks(doc_meta))
                    doc_meta["chunk_indices"] = list(range(current_idx, current_idx + n))
                    current_idx += n
            else:
                index = faiss.IndexFlatL2(self.embedding_dim)

            self._save_index(index, collection_name)
            metadata["chunk_count"] = index.ntotal
            _rebuild_chunk_lookup(metadata)

            # Keep the BM25 sidecar in sync — a stale one would fuse ranks
            # against FAISS indices that no longer line up.
            if config.RAG_USE_HYBRID_SEARCH:
                self._rebuild_bm25_index(collection_name, metadata)

            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

            return {
                "success": True,
                "collection_name": collection_name,
                "deleted_document": deleted_doc["name"],
                "deleted_chunks": deleted_chunks_count,
                "remaining_documents": len(metadata["documents"]),
                "remaining_chunks": metadata["chunk_count"],
            }
        except Exception as e:
            return {"success": False, "error": f"Error deleting document: {e}"}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_document_chunks(self, doc_meta: Dict[str, Any]) -> List[str]:
        if "chunks" in doc_meta:
            return doc_meta["chunks"]
        chunks_file = doc_meta.get("chunks_file")
        if chunks_file:
            return readers.load_chunks_from_disk(Path(chunks_file))
        return []

    def _rebuild_bm25_index(self, collection_name: str, metadata: dict):
        """Serialize the tokenized corpus so retrieve() can BM25-search without
        re-tokenizing every chunk on each call."""
        from tools.rag.retrieval import tokenize

        all_chunks = []
        for doc_meta in metadata["documents"].values():
            all_chunks.extend(self._get_document_chunks(doc_meta))

        bm25_path = self.user_index_dir / f"{collection_name}_bm25.json"
        if not all_chunks:
            if bm25_path.exists():
                bm25_path.unlink()
            return

        with open(bm25_path, 'w', encoding='utf-8') as f:
            json.dump({
                "chunk_count": len(all_chunks),
                "tokenized_corpus": [tokenize(chunk) for chunk in all_chunks],
            }, f)

    def _load_bm25(self, collection_name: str, metadata: dict):
        """Bind a BM25 instance for this collection to the hybrid retriever
        (mtime-cached per process). Returns None when no sidecar exists."""
        bm25_path = self.user_index_dir / f"{collection_name}_bm25.json"
        if not bm25_path.exists():
            print(f"[RAG] BM25 index not found for '{collection_name}', dense-only search")
            return None

        cache_key = f"{bm25_path}:{bm25_path.stat().st_mtime}"
        if cache_key in _GLOBAL_BM25_CACHE:
            self.hybrid_retriever.bm25 = _GLOBAL_BM25_CACHE[cache_key]
            return self.hybrid_retriever.bm25

        with open(bm25_path, 'r', encoding='utf-8') as f:
            bm25_data = json.load(f)
        tokenized_corpus = bm25_data.get("tokenized_corpus")
        if tokenized_corpus:
            from rank_bm25 import BM25Okapi
            bm25 = BM25Okapi(tokenized_corpus)
            for k in [k for k in _GLOBAL_BM25_CACHE if k.startswith(f"{bm25_path}:")]:
                del _GLOBAL_BM25_CACHE[k]
            _GLOBAL_BM25_CACHE[cache_key] = bm25
            self.hybrid_retriever.bm25 = bm25
            self.hybrid_retriever.tokenized_corpus = tokenized_corpus
        else:
            # Legacy sidecar without tokenized corpus: rebuild from chunks
            all_chunks = []
            for doc_meta in metadata["documents"].values():
                all_chunks.extend(self._get_document_chunks(doc_meta))
            self.hybrid_retriever.index_corpus(all_chunks)
        return self.hybrid_retriever.bm25

    def _new_index(self, dim: int):
        import faiss
        if config.RAG_INDEX_TYPE == "Flat" and config.RAG_SIMILARITY_METRIC == "cosine":
            return faiss.IndexFlatIP(dim)  # inner product == cosine on normalized vectors
        return faiss.IndexFlatL2(dim)

    def _load_or_create_index(self, collection_name: str, dim: int):
        import faiss
        index_path = self.user_index_dir / f"{collection_name}.index"
        if index_path.exists():
            return faiss.read_index(str(index_path))
        return self._new_index(dim)

    def _load_index(self, collection_name: str):
        """Load index via the process-level mtime cache (no disk read per request)."""
        import faiss
        index_path = self.user_index_dir / f"{collection_name}.index"
        if not index_path.exists():
            return None

        cache_key = f"{index_path}:{index_path.stat().st_mtime}"
        if cache_key in _GLOBAL_FAISS_CACHE:
            return _GLOBAL_FAISS_CACHE[cache_key]

        index = faiss.read_index(str(index_path))
        for k in [k for k in _GLOBAL_FAISS_CACHE if k.startswith(f"{index_path}:")]:
            del _GLOBAL_FAISS_CACHE[k]
        _GLOBAL_FAISS_CACHE[cache_key] = index
        return index

    def _save_index(self, index, collection_name: str):
        import faiss
        self.user_index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.user_index_dir / f"{collection_name}.index"))
