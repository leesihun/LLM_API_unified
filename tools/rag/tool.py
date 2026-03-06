"""
RAG (Retrieval-Augmented Generation) Tool
Uses FAISS for vector similarity search with configurable embeddings
"""
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import numpy as np

import config


def log_to_prompts_file(message: str):
    """Write message to prompts.log"""
    try:
        with open(config.PROMPTS_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(message + '\n')
    except Exception as e:
        print(f"[WARNING] Failed to write to prompts.log: {e}")


class RAGTool:
    """
    RAG tool with FAISS vector database
    Per-user collections with document upload and retrieval
    """

    def __init__(self, username: str):
        """
        Initialize RAG tool for a user

        Args:
            username: Username for collection isolation
        """
        self.username = username
        self.user_docs_dir = config.RAG_DOCUMENTS_DIR / username
        self.user_index_dir = config.RAG_INDEX_DIR / username
        self.user_metadata_dir = config.RAG_METADATA_DIR / username

        # Create directories
        self.user_docs_dir.mkdir(parents=True, exist_ok=True)
        self.user_index_dir.mkdir(parents=True, exist_ok=True)
        self.user_metadata_dir.mkdir(parents=True, exist_ok=True)

        # Load embedding model
        self.embedding_model = None  # Lazy load
        self.embedding_dim = None

    def _load_embedding_model(self):
        """Lazy load embedding model"""
        if self.embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )

            self.embedding_model = SentenceTransformer(
                config.RAG_EMBEDDING_MODEL,
                device=config.RAG_EMBEDDING_DEVICE
            )
            self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()

    def create_collection(self, collection_name: str) -> Dict[str, Any]:
        """
        Create a new document collection

        Args:
            collection_name: Name of the collection

        Returns:
            Result dictionary
        """
        collection_dir = self.user_docs_dir / collection_name
        index_path = self.user_index_dir / f"{collection_name}.index"
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"

        # Check if collection already exists with valid metadata
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    existing_metadata = json.load(f)
                return {
                    "success": False,
                    "error": f"Collection '{collection_name}' already exists with {len(existing_metadata.get('documents', {}))} documents"
                }
            except Exception:
                # Metadata file exists but is corrupted, recreate it
                print(f"[RAG] Warning: Corrupted metadata found for '{collection_name}', recreating...")

        # Create collection directory
        collection_dir.mkdir(parents=True, exist_ok=True)

        # Create empty metadata
        metadata = {
            "collection_name": collection_name,
            "created_at": time.time(),
            "documents": {},
            "chunk_count": 0
        }

        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create metadata file: {str(e)}"
            }

        return {
            "success": True,
            "collection_name": collection_name,
            "path": str(collection_dir)
        }

    def upload_document(
        self,
        collection_name: str,
        document_path: str,
        document_content: Optional[str] = None,
        document_name: Optional[str] = None,
        use_optimized: bool = True,
        progress_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Upload and index a document

        Args:
            collection_name: Collection to add to
            document_path: Path to document or document name
            document_content: Document content (if providing directly)
            document_name: Optional override for document name (useful when uploading from temp files)
            use_optimized: Use optimized uploader for PDFs (5-10x faster)
            progress_callback: Optional callback(message, progress_pct) for progress updates

        Returns:
            Upload result
        """
        # Check if this is a PDF and we should use optimized path
        doc_path = Path(document_path)
        if (use_optimized and 
            document_content is None and 
            doc_path.exists() and 
            doc_path.suffix.lower() == '.pdf'):
            
            print(f"[RAG] Using optimized PDF uploader for: {doc_path.name}")
            return self._upload_pdf_optimized(
                collection_name=collection_name,
                pdf_path=doc_path,
                document_name=document_name,
                progress_callback=progress_callback
            )
        
        # Standard upload path for non-PDFs or when optimization disabled
        self._load_embedding_model()

        collection_dir = self.user_docs_dir / collection_name
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"

        # Create collection if it doesn't exist
        if not collection_dir.exists():
            collection_dir.mkdir(parents=True, exist_ok=True)
            print(f"[RAG] Created new collection directory: {collection_dir}")

        # Load or create metadata
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                print(f"[RAG] Loaded existing metadata ({len(metadata.get('documents', {}))} documents)")
            except Exception as e:
                print(f"[RAG] Warning: Failed to load metadata, creating new: {e}")
                metadata = {
                    "collection_name": collection_name,
                    "created_at": time.time(),
                    "documents": {},
                    "chunk_count": 0
                }
        else:
            print(f"[RAG] Creating new metadata file")
            metadata = {
                "collection_name": collection_name,
                "created_at": time.time(),
                "documents": {},
                "chunk_count": 0
            }

        # Read document
        if document_content is None:
            doc_path = Path(document_path)
            if not doc_path.exists():
                return {"success": False, "error": "Document file not found"}

            if doc_path.suffix not in config.RAG_SUPPORTED_FORMATS:
                return {
                    "success": False,
                    "error": f"Unsupported format: {doc_path.suffix}"
                }

            document_content = self._read_document(doc_path)
            doc_name = document_name if document_name else doc_path.name
        else:
            doc_name = document_name if document_name else Path(document_path).name

        print(f"[RAG] Processing document: {doc_name}")

        # Chunk document
        print(f"[RAG] Chunking document...")
        chunks = self._chunk_text(document_content)
        print(f"[RAG] Created {len(chunks)} chunks")

        # Generate embeddings (normalized for cosine similarity with IndexFlatIP)
        print(f"[RAG] Generating embeddings...")
        embeddings = self.embedding_model.encode(
            chunks,
            batch_size=config.RAG_EMBEDDING_BATCH_SIZE,
            show_progress_bar=False,
            normalize_embeddings=True
        )
        print(f"[RAG] Generated {len(embeddings)} embeddings")

        # Load or create index
        print(f"[RAG] Loading/creating FAISS index...")
        index = self._load_or_create_index(collection_name, self.embedding_dim)
        print(f"[RAG] Index loaded (current size: {index.ntotal} vectors)")

        # Add to index
        start_idx = index.ntotal
        print(f"[RAG] Adding embeddings to index (indices {start_idx} to {start_idx + len(embeddings) - 1})...")
        index.add(np.array(embeddings).astype('float32'))
        print(f"[RAG] Index now has {index.ntotal} vectors")

        # Update metadata (include timestamp in hash to avoid collision on re-upload)
        upload_time = time.time()
        doc_id = hashlib.md5(f"{doc_name}:{upload_time}".encode()).hexdigest()
        metadata["documents"][doc_id] = {
            "name": doc_name,
            "path": str(document_path),
            "chunk_indices": list(range(start_idx, index.ntotal)),
            "chunks": chunks,
            "uploaded_at": upload_time
        }
        metadata["chunk_count"] = index.ntotal

        # Save index and metadata
        print(f"[RAG] Saving index to disk...")
        try:
            self._save_index(index, collection_name)
            print(f"[RAG] Index saved successfully")
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to save index: {str(e)}"
            }

        print(f"[RAG] Saving metadata to disk...")
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            print(f"[RAG] Metadata saved successfully")
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to save metadata: {str(e)}"
            }

        print(f"[RAG] Upload complete!")
        return {
            "success": True,
            "document_name": doc_name,
            "chunks_created": len(chunks),
            "total_chunks": index.ntotal
        }

    def retrieve(
        self,
        collection_name: str,
        query: str,
        max_results: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Retrieve relevant documents for a query

        Args:
            collection_name: Collection to search
            query: Search query
            max_results: Maximum results to return

        Returns:
            Retrieved documents
        """
        # Log to file
        log_to_prompts_file("\n\n")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file(f"TOOL EXECUTION: rag")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_to_prompts_file(f"")
        log_to_prompts_file(f"INPUT:")
        log_to_prompts_file(f"  Username: {self.username}")
        log_to_prompts_file(f"  Collection: {collection_name}")
        log_to_prompts_file(f"  Query: {query}")
        log_to_prompts_file(f"  Max Results: {max_results or 'default'}")

        print("\n" + "=" * 80)
        print("[RAG TOOL] retrieve() called")
        print("=" * 80)
        print(f"Username: {self.username}")
        print(f"Collection: {collection_name}")
        print(f"Query: {query}")
        print(f"Max results: {max_results or 'default'}")

        print(f"\n[RAG] Loading embedding model...")
        start_time = time.time()
        self._load_embedding_model()
        load_time = time.time() - start_time
        print(f"[RAG] [OK] Embedding model loaded ({load_time:.2f}s)")
        print(f"  Model: {config.RAG_EMBEDDING_MODEL}")
        print(f"  Dimension: {self.embedding_dim}")

        metadata_path = self.user_metadata_dir / f"{collection_name}.json"
        print(f"\n[RAG] Checking collection...")
        print(f"  Metadata path: {metadata_path}")

        if not metadata_path.exists():
            print(f"[RAG] [ERROR] Collection not found!")

            # Log to file
            log_to_prompts_file(f"")
            log_to_prompts_file(f"OUTPUT:")
            log_to_prompts_file(f"  Status: ERROR")
            log_to_prompts_file(f"  Error: Collection '{collection_name}' does not exist")
            log_to_prompts_file(f"")
            log_to_prompts_file("=" * 80)

            return {
                "success": False,
                "error": f"Collection '{collection_name}' does not exist"
            }
        
        print(f"[RAG] [OK] Collection found")

        # Load index and metadata
        print(f"\n[RAG] Loading FAISS index...")
        index = self._load_index(collection_name)
        if index is None:
            print(f"[RAG] [ERROR] Index not found!")

            # Log to file
            log_to_prompts_file(f"")
            log_to_prompts_file(f"OUTPUT:")
            log_to_prompts_file(f"  Status: ERROR")
            log_to_prompts_file(f"  Error: No index found for collection '{collection_name}'")
            log_to_prompts_file(f"")
            log_to_prompts_file("=" * 80)

            return {
                "success": False,
                "error": f"No index found for collection '{collection_name}'"
            }
        print(f"[RAG] [OK] Index loaded")
        print(f"  Total vectors: {index.ntotal}")

        print(f"\n[RAG] Loading metadata...")
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        print(f"[RAG] [OK] Metadata loaded")
        print(f"  Documents: {len(metadata.get('documents', {}))}")
        print(f"  Chunks: {metadata.get('chunk_count', 0)}")

        if index.ntotal == 0:
            print(f"[RAG] [WARNING] Collection is empty")
            return {
                "success": True,
                "documents": [],
                "message": "Collection is empty"
            }

        # Generate query embedding
        print(f"\n[RAG] Generating query embedding...")
        embed_start = time.time()
        query_embedding = self.embedding_model.encode(
            [config.RAG_QUERY_PREFIX + query],
            normalize_embeddings=True
        )[0]
        embed_time = time.time() - embed_start
        print(f"[RAG] [OK] Query embedding generated ({embed_time:.2f}s)")
        print(f"  Embedding shape: {query_embedding.shape}")

        # Search
        k = min(max_results or config.RAG_MAX_RESULTS, index.ntotal)
        print(f"\n[RAG] Searching FAISS index...")
        print(f"  K (results to retrieve): {k}")
        
        search_start = time.time()
        distances, indices = index.search(
            np.array([query_embedding]).astype('float32'),
            k
        )
        search_time = time.time() - search_start
        print(f"[RAG] [OK] Search completed ({search_time:.2f}s)")
        print(f"  Distances: {distances[0].tolist()}")
        print(f"  Indices: {indices[0].tolist()}")

        # Retrieve chunks with context window
        print(f"\n[RAG] Retrieving document chunks (context_window={config.RAG_CONTEXT_WINDOW})...")
        results = []
        for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            # Skip invalid FAISS indices (FAISS returns -1 for empty slots when k > ntotal)
            if idx < 0:
                continue

            # Find document containing this chunk
            for doc_id, doc_meta in metadata["documents"].items():
                if idx in doc_meta["chunk_indices"]:
                    chunk_local_idx = doc_meta["chunk_indices"].index(idx)
                    if config.RAG_SIMILARITY_METRIC == "cosine":
                        # IndexFlatIP returns cosine similarity directly (higher = better)
                        score = float(dist)
                    else:
                        # L2 distance: convert to similarity (lower distance = higher score)
                        score = float(1 / (1 + dist))
                    chunk_text = doc_meta["chunks"][chunk_local_idx]

                    # Build context window from neighboring chunks
                    context_chunks = []
                    total_chunks = len(doc_meta["chunks"])
                    window = config.RAG_CONTEXT_WINDOW
                    start_ctx = max(0, chunk_local_idx - window)
                    end_ctx = min(total_chunks, chunk_local_idx + window + 1)

                    for ctx_idx in range(start_ctx, end_ctx):
                        context_chunks.append(doc_meta["chunks"][ctx_idx])

                    chunk_with_context = "\n---\n".join(context_chunks)

                    results.append({
                        "document": doc_meta["name"],
                        "chunk": chunk_with_context,
                        "score": score,
                        "chunk_index": chunk_local_idx
                    })
                    
                    print(f"  Result {i+1}: {doc_meta['name']} chunk {chunk_local_idx} (score: {score:.3f})")
                    print(f"    Context: chunks {start_ctx}-{end_ctx-1}, Preview: {chunk_text[:100]}...")
                    break

        # Filter out low-relevance results
        pre_filter_count = len(results)
        results = [r for r in results if r["score"] >= config.RAG_MIN_SCORE_THRESHOLD]
        filtered_count = pre_filter_count - len(results)
        if filtered_count > 0:
            print(f"\n[RAG] Filtered {filtered_count} results below score threshold ({config.RAG_MIN_SCORE_THRESHOLD})")

        print(f"\n[RAG] [OK] Retrieved {len(results)} results")
        total_time = time.time() - start_time
        print(f"[RAG] Total time: {total_time:.2f}s")

        # Log to file
        log_to_prompts_file(f"")
        log_to_prompts_file(f"OUTPUT:")
        log_to_prompts_file(f"  Status: SUCCESS")
        log_to_prompts_file(f"  Results Found: {len(results)}")
        log_to_prompts_file(f"  Execution Time: {total_time:.2f}s")
        log_to_prompts_file(f"")
        log_to_prompts_file(f"RESULTS:")
        for i, result in enumerate(results, 1):
            log_to_prompts_file(f"")
            log_to_prompts_file(f"  Result {i}:")
            log_to_prompts_file(f"    Document: {result['document']}")
            log_to_prompts_file(f"    Chunk Index: {result['chunk_index']}")
            log_to_prompts_file(f"    Score: {result['score']:.3f}")
            chunk_preview = result['chunk'][:200] if len(result['chunk']) > 200 else result['chunk']
            log_to_prompts_file(f"    Content: {chunk_preview}...")
        log_to_prompts_file(f"")
        log_to_prompts_file("=" * 80)

        return {
            "success": True,
            "documents": results,
            "query": query,
            "num_results": len(results)
        }

    def list_collections(self) -> Dict[str, Any]:
        """
        List all collections for user

        Returns:
            List of collections
        """
        collections = []

        for metadata_file in self.user_metadata_dir.glob("*.json"):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                collections.append({
                    "name": metadata["collection_name"],
                    "documents": len(metadata["documents"]),
                    "chunks": metadata["chunk_count"],
                    "created_at": metadata["created_at"]
                })
            except Exception:
                continue

        return {
            "success": True,
            "collections": collections
        }

    def delete_collection(self, collection_name: str) -> Dict[str, Any]:
        """
        Delete a collection

        Args:
            collection_name: Collection to delete

        Returns:
            Result dictionary
        """
        import shutil

        collection_dir = self.user_docs_dir / collection_name
        index_path = self.user_index_dir / f"{collection_name}.index"
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"

        if not metadata_path.exists():
            return {
                "success": False,
                "error": f"Collection '{collection_name}' does not exist"
            }

        # Delete all files
        if collection_dir.exists():
            shutil.rmtree(collection_dir)
        if index_path.exists():
            index_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()

        return {
            "success": True,
            "collection_name": collection_name
        }

    def list_documents(self, collection_name: str) -> Dict[str, Any]:
        """
        List all documents in a collection

        Args:
            collection_name: Collection to list documents from

        Returns:
            List of documents with metadata
        """
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"

        if not metadata_path.exists():
            return {
                "success": False,
                "error": f"Collection '{collection_name}' does not exist"
            }

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            documents = []
            for doc_id, doc_meta in metadata.get("documents", {}).items():
                documents.append({
                    "id": doc_id,
                    "name": doc_meta["name"],
                    "path": doc_meta["path"],
                    "chunks": len(doc_meta["chunks"]),
                    "uploaded_at": doc_meta["uploaded_at"]
                })

            return {
                "success": True,
                "collection_name": collection_name,
                "documents": documents,
                "total_documents": len(documents),
                "total_chunks": metadata.get("chunk_count", 0)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error listing documents: {str(e)}"
            }

    def delete_document(self, collection_name: str, document_id: str) -> Dict[str, Any]:
        """
        Delete a specific document from a collection
        Note: This rebuilds the FAISS index without the deleted document

        Args:
            collection_name: Collection containing the document
            document_id: ID of document to delete

        Returns:
            Result dictionary
        """
        metadata_path = self.user_metadata_dir / f"{collection_name}.json"

        if not metadata_path.exists():
            return {
                "success": False,
                "error": f"Collection '{collection_name}' does not exist"
            }

        try:
            # Load metadata
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            # Check if document exists
            if document_id not in metadata["documents"]:
                return {
                    "success": False,
                    "error": f"Document '{document_id}' not found in collection"
                }

            # Get document info before deletion
            deleted_doc = metadata["documents"][document_id]
            deleted_doc_name = deleted_doc["name"]
            deleted_chunks_count = len(deleted_doc["chunks"])

            # Remove document from metadata
            del metadata["documents"][document_id]

            # Rebuild FAISS index without deleted document
            self._load_embedding_model()

            # Collect all remaining chunks and embeddings
            all_chunks = []
            for doc_id, doc_meta in metadata["documents"].items():
                all_chunks.extend(doc_meta["chunks"])

            if len(all_chunks) > 0:
                # Re-generate embeddings for all remaining documents
                embeddings = self.embedding_model.encode(
                    all_chunks,
                    batch_size=config.RAG_EMBEDDING_BATCH_SIZE,
                    show_progress_bar=False,
                    normalize_embeddings=True
                )

                # Create new index
                import faiss
                if config.RAG_INDEX_TYPE == "Flat":
                    if config.RAG_SIMILARITY_METRIC == "cosine":
                        index = faiss.IndexFlatIP(self.embedding_dim)
                    else:
                        index = faiss.IndexFlatL2(self.embedding_dim)
                else:
                    index = faiss.IndexFlatL2(self.embedding_dim)

                # Add all embeddings
                index.add(np.array(embeddings).astype('float32'))

                # Update chunk indices for remaining documents
                current_idx = 0
                for doc_id, doc_meta in metadata["documents"].items():
                    chunk_count = len(doc_meta["chunks"])
                    doc_meta["chunk_indices"] = list(range(current_idx, current_idx + chunk_count))
                    current_idx += chunk_count

                # Save updated index
                self._save_index(index, collection_name)
                metadata["chunk_count"] = index.ntotal
            else:
                # No documents left - create empty index
                import faiss
                index = faiss.IndexFlatL2(self.embedding_dim)
                self._save_index(index, collection_name)
                metadata["chunk_count"] = 0

            # Save updated metadata
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

            return {
                "success": True,
                "collection_name": collection_name,
                "deleted_document": deleted_doc_name,
                "deleted_chunks": deleted_chunks_count,
                "remaining_documents": len(metadata["documents"]),
                "remaining_chunks": metadata["chunk_count"]
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error deleting document: {str(e)}"
            }

    def _chunk_text(self, text: str) -> List[str]:
        """
        Split text into chunks

        Args:
            text: Text to chunk

        Returns:
            List of chunks
        """
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

    def _read_document(self, path: Path) -> str:
        """
        Read document content based on file type

        Args:
            path: Document path

        Returns:
            Document text
        """
        if path.suffix in ['.txt', '.md']:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()

        elif path.suffix == '.json':
            with open(path, 'r', encoding='utf-8') as f:
                return json.dumps(json.load(f), indent=2)

        elif path.suffix == '.csv':
            import pandas as pd
            df = pd.read_csv(path)
            return df.to_string()

        elif path.suffix in ['.xlsx', '.xls']:
            import pandas as pd
            excel_file = pd.ExcelFile(path)
            parts = []
            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(path, sheet_name=sheet_name)
                parts.append(f"[Sheet: {sheet_name}]")
                parts.append(df.to_string())
            return '\n\n'.join(parts)

        elif path.suffix == '.pdf':
            # Use fast PDF reader
            try:
                from tools.rag.optimized_uploader import read_pdf_fast
                return read_pdf_fast(path)
            except Exception as e:
                print(f"[RAG] Fast PDF reader failed, falling back to PyPDFLoader: {e}")
                from langchain_community.document_loaders import PyPDFLoader
                loader = PyPDFLoader(str(path))
                pages = loader.load()
                return '\n'.join(page.page_content for page in pages)

        elif path.suffix == '.docx':
            from docx import Document
            doc = Document(path)
            parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text)
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    parts.append(' | '.join(cells))
            return '\n'.join(parts)

        else:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()

    def _load_or_create_index(self, collection_name: str, dim: int):
        """Load existing index or create new one"""
        import faiss

        index_path = self.user_index_dir / f"{collection_name}.index"

        if index_path.exists():
            return faiss.read_index(str(index_path))
        else:
            # Create new index based on config
            if config.RAG_INDEX_TYPE == "Flat":
                if config.RAG_SIMILARITY_METRIC == "cosine":
                    index = faiss.IndexFlatIP(dim)  # Inner product for cosine
                else:
                    index = faiss.IndexFlatL2(dim)
            else:
                # Default to Flat
                index = faiss.IndexFlatL2(dim)

            return index

    def _load_index(self, collection_name: str):
        """Load index"""
        import faiss

        index_path = self.user_index_dir / f"{collection_name}.index"

        if index_path.exists():
            return faiss.read_index(str(index_path))
        return None

    def _save_index(self, index, collection_name: str):
        """Save index"""
        import faiss

        # Ensure index directory exists
        self.user_index_dir.mkdir(parents=True, exist_ok=True)

        index_path = self.user_index_dir / f"{collection_name}.index"
        faiss.write_index(index, str(index_path))
    
    def _upload_pdf_optimized(
        self,
        collection_name: str,
        pdf_path: Path,
        document_name: Optional[str] = None,
        progress_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Upload PDF using optimized parallel processing
        
        Args:
            collection_name: Target collection
            pdf_path: Path to PDF file
            document_name: Optional override for document name
            progress_callback: Optional callback(message, progress_pct) for progress updates
            
        Returns:
            Upload result
        """
        from tools.rag.optimized_uploader import OptimizedRAGUploader
        
        self._load_embedding_model()
        
        # Create collection if it doesn't exist
        collection_dir = self.user_docs_dir / collection_name
        if not collection_dir.exists():
            collection_dir.mkdir(parents=True, exist_ok=True)
            print(f"[RAG] Created new collection directory: {collection_dir}")
        
        # Initialize optimized uploader
        uploader = OptimizedRAGUploader(
            embedding_model=self.embedding_model,
            embedding_dim=self.embedding_dim,
            max_workers=None,  # Use all CPU cores
            pages_per_batch=20  # Process 20 pages per worker
        )
        
        try:
            result = uploader.upload_pdf_optimized(
                pdf_path=pdf_path,
                collection_name=collection_name,
                user_docs_dir=self.user_docs_dir,
                user_index_dir=self.user_index_dir,
                user_metadata_dir=self.user_metadata_dir,
                document_name=document_name,
                progress_callback=progress_callback,
                show_progress_bar=True  # Enable text-based progress bar by default
            )
            return result
            
        except Exception as e:
            print(f"[RAG] Optimized upload failed: {e}")
            print(f"[RAG] Falling back to standard upload method")
            
            # Fallback to standard method
            return self.upload_document(
                collection_name=collection_name,
                document_path=str(pdf_path),
                document_content=None,
                document_name=document_name,
                use_optimized=False  # Prevent infinite recursion
            )
