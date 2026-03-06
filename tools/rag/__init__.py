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

__all__ = ["RAGTool", "BaseRAGTool", "EnhancedRAGTool"]
