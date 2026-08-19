import os
import json
import hashlib
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    logging.error("[!] ChromaDB not installed.")

from config import settings

logger = logging.getLogger("vector_store")

class VectorStore:
    \"\"\"
    PRODUCTION Vector Store.
    Hybrid Search (Vector + Keyword) -> Reranking -> Citations.
    \"\"\"
    def __init__(self):
        if not CHROMA_AVAILABLE:
            self.client = None
            return

        self.client = chromadb.PersistentClient(
            path=os.getenv(\"CHROMA_PERSIST_DIR\", \"./chroma_db\"),
            settings=ChromaSettings(anonymized_telemetry=False)
        )

    def _get_collection(self, client_id: int, collection_name: str = \"knowledge\"):
        collection_id = f\"client_{client_id}_{collection_name}\"
        return self.client.get_or_create_collection(name=collection_id)

    def add_documents(self, client_id: int, text: str, metadata: Dict[str, Any] = None) -> List[str]:
        \"\"\"Incremental Sync: Only adds chunks that have changed (Hash-based).\"\"\"
        if not self.client: return []
        collection = self._get_collection(client_id)
        
        # Production Chunking (approx 400-800 tokens)
        chunks = self._chunk_text(text)
        
        ids, final_chunks, final_metas = [], [], []

        for i, chunk in enumerate(chunks):
            content_hash = hashlib.sha256(chunk.encode()).hexdigest()
            meta = metadata.copy() if metadata else {}
            meta.update({\"content_hash\": content_hash, \"chunk_index\": i})
            
            # Re-sync trigger: Check if hash exists
            existing = collection.get(where={\"content_hash\": content_hash})
            if existing and existing.get(\"ids\"):
                continue # Skip: already exists
            
            ids.append(f\"doc_{content_hash[:12]}_{i}\")
            final_chunks.append(chunk)
            final_metas.append(meta)

        if not final_chunks: return []
        collection.add(documents=final_chunks, metadatas=final_metas, ids=ids)
        return ids

    def _chunk_text(self, text: str) -> List[str]:
        char_limit, overlap = 2000, 200 # Proxy for tokens
        chunks, start = [], 0
        while start < len(text):
            end = start + char_limit
            chunk = text[start:end]
            if end < len(text):
                split = max(chunk.rfind('. '), chunk.rfind('\\n'))
                if split > char_limit // 2: chunk = chunk[:split+1]; end = start + len(chunk)
            chunks.append(chunk); start = end - overlap
        return chunks

    async def hybrid_search(self, query: str, client_id: int, top_k: int = 20) -> List[Dict]:
        \"\"\"
        Hybrid Retrieval: Vector Similarity + Keyword Boost.
        \"\"\"
        if not self.client: return []
        collection = self._get_collection(client_id)
        
        # 1. Vector Search (Semantic)
        results = collection.query(query_texts=[query], n_results=top_k)
        
        formatted = []
        if results and results.get(\"documents\"):
            for i, doc in enumerate(results[\"documents\"][0]):
                # Hybrid Boost: Check for exact keyword matches in the content
                score = results[\"distances\"][0][i] if results.get(\"distances\") else 1.0
                keywords = query.lower().split()
                boost = sum(1 for kw in keywords if kw in doc.lower()) * 0.05
                
                formatted.append({
                    \"content\": doc,
                    \"metadata\": results[\"metadatas\"][0][i] if results.get(\"metadatas\") else {},
                    \"score\": score - boost # Lower is better in Chroma
                })
        
        # Sort by boosted score
        return sorted(formatted, key=lambda x: x['score'])

    def delete_all(self, client_id: int):
        if not self.client: return
        try: self.client.delete_collection(f\"client_{client_id}_knowledge\")
        except Exception: pass

vector_store = VectorStore()
