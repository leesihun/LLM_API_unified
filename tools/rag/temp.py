"""
Offline Model Download Script for RAG

Run this on a machine with internet access, then copy the saved
model directories to /scratch0/LLM_models/offline_models/ on the server.

Models:
  1. BAAI/bge-m3           - Multilingual embedding (Korean + English + 100 languages, 1024 dim, ~2.3GB)
  2. mmarco-mMiniLMv2      - Multilingual cross-encoder reranker (trained on mMARCO multilingual QA)
"""
from sentence_transformers import SentenceTransformer, CrossEncoder

SAVE_DIR = r"C:\Users\Lee\Desktop\offline_models"

# 1. Multilingual embedding model (~2.3GB download)
print("Downloading multilingual embedding model (BAAI/bge-m3)...")
embed = SentenceTransformer("BAAI/bge-m3")
embed.save(f"{SAVE_DIR}/bge-m3")
print("Saved embedding model.")

# 2. Multilingual reranker model (~130MB download)
print("Downloading multilingual reranker model (mmarco-mMiniLMv2-L12-H384-v1)...")
reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
reranker.save(f"{SAVE_DIR}/mmarco-mMiniLMv2-L12-H384-v1")
print("Saved reranker model.")