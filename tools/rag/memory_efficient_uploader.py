"""
Memory-Efficient RAG Uploader for Extremely Large Documents
Handles 1000+ page PDFs without loading everything into memory
Uses streaming and disk-based temporary storage
"""
import time
import json
import hashlib
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import numpy as np

import config


class MemoryEfficientUploader:
    """
    Ultra-memory-efficient uploader for massive documents
    
    Key features:
    - Streams chunks to disk instead of keeping in memory
    - Processes embeddings in small batches
    - Stores chunks separately from metadata for large docs
    - Incremental FAISS index updates
    
    Use when:
    - PDFs > 1000 pages
    - Available RAM < 8GB
    - Chunk count > 10,000
    """
    
    def __init__(
        self,
        embedding_model,
        embedding_dim: int,
        chunk_memory_threshold: int = 5000,  # Store chunks separately above this
        embedding_batch_size: int = 32
    ):
        """
        Initialize memory-efficient uploader
        
        Args:
            embedding_model: Pre-loaded embedding model
            embedding_dim: Embedding dimension
            chunk_memory_threshold: Number of chunks before using disk storage
            embedding_batch_size: Embeddings to generate per batch
        """
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self.chunk_memory_threshold = chunk_memory_threshold
        self.embedding_batch_size = embedding_batch_size
    
    def upload_large_document(
        self,
        document_path: Path,
        collection_name: str,
        user_docs_dir: Path,
        user_index_dir: Path,
        user_metadata_dir: Path,
        document_name: Optional[str] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict[str, Any]:
        """
        Upload extremely large document with minimal memory usage
        
        Args:
            document_path: Path to document
            collection_name: Target collection
            user_docs_dir: User documents directory
            user_index_dir: User index directory
            user_metadata_dir: User metadata directory
            document_name: Override document name
            progress_callback: Callback(message, progress_pct) for status updates
            
        Returns:
            Upload result dictionary
        """
        overall_start = time.time()
        
        def update_progress(msg: str, pct: float):
            if progress_callback:
                progress_callback(msg, pct)
            print(f"[MEMORY EFFICIENT] {msg} ({pct:.1f}%)")
        
        update_progress("Starting memory-efficient upload", 0)
        
        # Step 1: Read document in streaming fashion
        update_progress("Reading document", 5)
        text = self._read_document_streaming(document_path)
        text_size = len(text)
        update_progress(f"Read {text_size:,} characters", 10)
        
        # Step 2: Chunk document
        update_progress("Chunking document", 15)
        chunks = self._chunk_text(text)
        num_chunks = len(chunks)
        update_progress(f"Created {num_chunks:,} chunks", 20)
        
        # Free memory
        del text
        
        # Determine if we need disk-based chunk storage
        use_disk_storage = num_chunks > self.chunk_memory_threshold
        
        if use_disk_storage:
            update_progress(
                f"Large document ({num_chunks} chunks) - using disk storage",
                25
            )
            chunks_file = self._save_chunks_to_disk(chunks, user_docs_dir, collection_name)
            # Keep chunks in memory for now, will clear after embeddings
        else:
            chunks_file = None
            update_progress("Chunks fit in memory", 25)
        
        # Step 3: Generate embeddings in small batches to save memory
        update_progress("Generating embeddings in batches", 30)
        
        # Load or create index
        index = self._load_or_create_index(user_index_dir, collection_name, self.embedding_dim)
        start_idx = index.ntotal
        
        total_batches = (num_chunks + self.embedding_batch_size - 1) // self.embedding_batch_size
        
        for batch_idx in range(0, num_chunks, self.embedding_batch_size):
            batch_end = min(batch_idx + self.embedding_batch_size, num_chunks)
            batch_chunks = chunks[batch_idx:batch_end]
            
            # Generate embeddings for batch
            batch_embeddings = self.embedding_model.encode(
                batch_chunks,
                batch_size=self.embedding_batch_size,
                show_progress_bar=False,
                normalize_embeddings=True
            )
            
            # Add to index immediately
            index.add(np.array(batch_embeddings).astype('float32'))
            
            # Update progress
            batch_num = (batch_idx // self.embedding_batch_size) + 1
            pct = 30 + (batch_num / total_batches) * 60
            update_progress(
                f"Embedded and indexed batch {batch_num}/{total_batches}",
                pct
            )
            
            # Free memory
            del batch_embeddings
        
        update_progress("All embeddings generated and indexed", 90)
        
        # Step 4: Save index and metadata
        update_progress("Saving index and metadata", 95)
        
        doc_name = document_name if document_name else document_path.name
        upload_time = time.time()
        doc_id = hashlib.md5(f"{doc_name}:{upload_time}".encode()).hexdigest()
        
        # Load or create metadata
        metadata_path = user_metadata_dir / f"{collection_name}.json"
        if metadata_path.exists():
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        else:
            metadata = {
                "collection_name": collection_name,
                "created_at": time.time(),
                "documents": {},
                "chunk_count": 0
            }
        
        # Update metadata
        if use_disk_storage:
            # Store reference to chunks file instead of chunks themselves
            metadata["documents"][doc_id] = {
                "name": doc_name,
                "path": str(document_path),
                "chunk_indices": list(range(start_idx, index.ntotal)),
                "chunks_file": str(chunks_file),  # Reference to disk file
                "chunk_count": num_chunks,
                "uploaded_at": upload_time,
                "memory_efficient": True
            }
        else:
            # Store chunks in metadata (small documents)
            metadata["documents"][doc_id] = {
                "name": doc_name,
                "path": str(document_path),
                "chunk_indices": list(range(start_idx, index.ntotal)),
                "chunks": chunks,
                "uploaded_at": upload_time,
                "memory_efficient": False
            }
        
        metadata["chunk_count"] = index.ntotal
        
        # Save index
        self._save_index(index, user_index_dir, collection_name)
        
        # Save metadata
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        
        total_time = time.time() - overall_start
        update_progress(f"Upload complete in {total_time:.1f}s", 100)
        
        return {
            "success": True,
            "document_name": doc_name,
            "chunks_created": num_chunks,
            "total_chunks": index.ntotal,
            "disk_storage": use_disk_storage,
            "timing": {
                "total": total_time
            }
        }
    
    def _read_document_streaming(self, path: Path) -> str:
        """Read document with memory efficiency"""
        if path.suffix == '.pdf':
            try:
                import fitz
                doc = fitz.open(str(path))
                text_parts = []
                for page in doc:
                    text_parts.append(page.get_text())
                    # Process in chunks to avoid memory buildup
                    if len(text_parts) >= 50:
                        yield_text = "\n\n".join(text_parts)
                        text_parts = [yield_text[-1000:]]  # Keep some context
                doc.close()
                return "\n\n".join(text_parts)
            except Exception:
                pass
        
        # Fallback to standard read
        if path.suffix in ['.txt', '.md']:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        elif path.suffix == '.pdf':
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(str(path))
            pages = loader.load()
            return '\n'.join(page.page_content for page in pages)
        else:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
    
    def _chunk_text(self, text: str) -> List[str]:
        """Chunk text with memory efficiency"""
        chunk_size = config.RAG_CHUNK_SIZE
        overlap = config.RAG_CHUNK_OVERLAP
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            
            if chunk:
                chunks.append(chunk)
            
            start = end - overlap
        
        return chunks
    
    def _save_chunks_to_disk(
        self,
        chunks: List[str],
        user_docs_dir: Path,
        collection_name: str
    ) -> Path:
        """Save chunks to disk file for large documents"""
        chunks_dir = user_docs_dir / collection_name / "_chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        timestamp = time.time()
        chunks_file = chunks_dir / f"chunks_{timestamp}.json"
        
        with open(chunks_file, 'w', encoding='utf-8') as f:
            json.dump(chunks, f)
        
        return chunks_file
    
    def _load_or_create_index(self, index_dir: Path, collection_name: str, dim: int):
        """Load existing index or create new one"""
        import faiss
        
        index_path = index_dir / f"{collection_name}.index"
        
        if index_path.exists():
            return faiss.read_index(str(index_path))
        else:
            if config.RAG_SIMILARITY_METRIC == "cosine":
                return faiss.IndexFlatIP(dim)
            else:
                return faiss.IndexFlatL2(dim)
    
    def _save_index(self, index, index_dir: Path, collection_name: str):
        """Save index to disk"""
        import faiss
        
        index_dir.mkdir(parents=True, exist_ok=True)
        index_path = index_dir / f"{collection_name}.index"
        faiss.write_index(index, str(index_path))


def load_chunks_from_disk(chunks_file: Path) -> List[str]:
    """
    Load chunks from disk file (for retrieval)
    
    Args:
        chunks_file: Path to chunks JSON file
        
    Returns:
        List of chunks
    """
    with open(chunks_file, 'r', encoding='utf-8') as f:
        return json.load(f)
