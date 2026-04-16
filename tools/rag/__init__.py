"""
RAG Tool with FAISS vector database

To use the enhanced RAG with hybrid search and reranking:
- Set RAG_USE_HYBRID_SEARCH = True in config.py
- Set RAG_USE_RERANKING = True in config.py
- Set RAG_CHUNKING_STRATEGY = "semantic" in config.py
"""
from tools.rag.tool import RAGTool as BaseRAGTool
from tools.rag.enhanced_tool import EnhancedRAGTool

# Import based on config - use Enhanced if any advanced features enabled
import config

if (config.RAG_USE_HYBRID_SEARCH or
    config.RAG_USE_RERANKING or
    config.RAG_CHUNKING_STRATEGY != "fixed"):
    RAGTool = EnhancedRAGTool
    print("[RAG] Using EnhancedRAGTool (advanced features enabled)")
else:
    RAGTool = BaseRAGTool
    print("[RAG] Using BaseRAGTool (basic mode)")

def preload_models():
    """Pre-load embedding model (and reranker/chunker for enhanced mode) at startup
    so the first RAG request doesn't pay the multi-second model-loading penalty.

    Uses a throwaway instance with a dummy username — __init__ only creates
    dirs (harmless), and the _load_* methods populate the process-level singletons
    that all future instances will reuse."""
    print("[RAG preload] Loading models...")
    loader = RAGTool(username="__preload__")
    loader._load_embedding_model()
    print("[RAG preload] Embedding model ready")

    if RAGTool is EnhancedRAGTool:
        if config.RAG_USE_RERANKING:
            loader._load_reranker()
            print("[RAG preload] Reranker ready")

    loader.cleanup()

    # Remove empty dirs created by the dummy instance
    import shutil
    for base in (config.RAG_DOCUMENTS_DIR, config.RAG_INDEX_DIR, config.RAG_METADATA_DIR):
        dummy_dir = base / "__preload__"
        if dummy_dir.exists() and not any(dummy_dir.iterdir()):
            shutil.rmtree(dummy_dir, ignore_errors=True)

    print("[RAG preload] Done")


__all__ = ["RAGTool", "BaseRAGTool", "EnhancedRAGTool", "preload_models"]
