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

try:
    from sentence_transformers import CrossEncoder
    RERANKER_AVAILABLE = True
except ImportError:
    RERANKER_AVAILABLE = False
    logging.warning("[!] sentence-transformers not installed. Reranking disabled.")

from config import settings

logger = logging.getLogger("vector_store")

class VectorStore:
    """
    PRODUCTION Vector Store.
    Hybrid Search (Vector + Keyword) -> Reranking -> Citations.
    """
    def __init__(self):
        if not CHROMA_AVAILABLE:
            self.client = None
            return

        self.client = chromadb.PersistentClient(
            path=os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"),
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        # Initialize reranker (cross-encoder for reranking)
        self._reranker = None
        if RERANKER_AVAILABLE:
            try:
                self._reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
                logger.info("[v] Cross-encoder reranker loaded")
            except Exception as e:
                logger.warning(f"[!] Failed to load reranker: {e}")
                self._reranker = None

    def _get_collection(self, client_id: int, collection_name: str = "knowledge"):
        collection_id = f"client_{client_id}_{collection_name}"
        return self.client.get_or_create_collection(name=collection_id)

    def add_documents(self, client_id: int, text: str, metadata: Dict[str, Any] = None) -> List[str]:
        """Incremental Sync: Only adds chunks that have changed (Hash-based)."""
        if not self.client: return []
        collection = self._get_collection(client_id)
        
        # Production Chunking (approx 400-800 tokens)
        chunks = self._chunk_text(text)
        
        ids, final_chunks, final_metas = [], [], []

        for i, chunk in enumerate(chunks):
            content_hash = hashlib.sha256(chunk.encode()).hexdigest()
            meta = metadata.copy() if metadata else {}
            meta.update({"content_hash": content_hash, "chunk_index": i})
            
            # Re-sync trigger: Check if hash exists
            existing = collection.get(where={"content_hash": content_hash})
            if existing and existing.get("ids"):
                continue # Skip: already exists
            
            ids.append(f"doc_{content_hash[:12]}_{i}")
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
                split = max(chunk.rfind('. '), chunk.rfind('\n'))
                if split > char_limit // 2: chunk = chunk[:split+1]; end = start + len(chunk)
            chunks.append(chunk); start = end - overlap
        return chunks

    async def hybrid_search(self, query: str, client_id: int, top_k: int = 20) -> List[Dict]:
        """
        Hybrid Retrieval: Vector Similarity + Keyword Boost + Cross-encoder Reranking.
        """
        if not self.client: return []
        collection = self._get_collection(client_id)
        
        # 1. Vector Search (Semantic) - fetch more candidates for reranking
        rerank_k = min(top_k * 3, 50)  # Fetch more candidates for reranking
        results = collection.query(query_texts=[query], n_results=rerank_k)
        
        formatted = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                # Hybrid Boost: Check for exact keyword matches in the content
                score = results["distances"][0][i] if results.get("distances") else 1.0
                keywords = query.lower().split()
                boost = sum(1 for kw in keywords if kw in doc.lower()) * 0.05
                
                formatted.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "score": score - boost,  # Lower is better in Chroma
                    "doc_id": results["ids"][0][i] if results.get("ids") else f"doc_{i}"
                })
        
        # Sort by boosted score (pre-reranking)
        formatted.sort(key=lambda x: x['score'])
        
        # 2. Cross-encoder Reranking (if available)
        if self._reranker and formatted:
            formatted = await self._rerank_results(query, formatted, top_k)
        
        return formatted[:top_k]

    async def _rerank_results(self, query: str, candidates: List[Dict], top_k: int) -> List[Dict]:
        """Rerank candidates using cross-encoder."""
        try:
            # Prepare pairs for cross-encoder
            pairs = [(query, c["content"][:512]) for c in candidates]  # Truncate content
            
            # Run reranking in thread pool to avoid blocking
            import asyncio
            scores = await asyncio.to_thread(self._reranker.predict, pairs)
            
            # Add rerank scores
            for i, candidate in enumerate(candidates):
                candidate["rerank_score"] = float(scores[i]) if i < len(scores) else 0.0
            
            # Sort by rerank score (higher is better for cross-encoder)
            candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
            logger.debug(f"Reranked {len(candidates)} candidates")
        except Exception as e:
            logger.warning(f"Reranking failed: {e}")
        
        return candidates

    def delete_all(self, client_id: int):
        if not self.client: return
        try: self.client.delete_collection(f"client_{client_id}_knowledge")
        except Exception: pass

vector_store = VectorStore()
