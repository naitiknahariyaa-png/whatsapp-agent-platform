"""
RAG Pipeline - Document ingestion, retrieval, and freshness guard
"""
import os
import re
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("rag_pipeline")

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents")
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def get_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= chunk_size:
        return [cleaned]
    chunks = []
    start = 0
    while start < len(cleaned):
        end = start + chunk_size
        chunk = cleaned[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks


class RAGPipeline:
    def __init__(self):
        from vector_store import add_documents, search_knowledge, get_collection_stats
        from tool_registry import tool_registry
        self.add_documents = add_documents
        self.search_knowledge = search_knowledge
        self.get_collection_stats = get_collection_stats
        self.tool_registry = tool_registry

    async def ingest_document(self, client_id: int, file_path: str, category: str = "general", tags: List[str] = None):
        if not os.path.exists(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            return {"status": "error", "message": str(e)}

        chunks = _chunk_text(text)
        if not chunks:
            return {"status": "error", "message": "No content extracted from document."}

        documents = []
        metadatas = []
        ids = []
        now = datetime.utcnow().isoformat()
        for idx, chunk in enumerate(chunks):
            chunk_hash = get_content_hash(chunk + str(client_id))
            documents.append(chunk)
            metadatas.append({
                "client_id": client_id,
                "category": category,
                "tags": tags or [],
                "chunk_index": idx,
                "source_file": os.path.basename(file_path),
                "content_hash": chunk_hash,
                "created_at": now,
            })
            ids.append(f"{client_id}_{os.path.basename(file_path)}_{idx}_{chunk_hash[:12]}")

        existing = self.search_knowledge(client_id, chunks[0][:100], n_results=5)
        existing_hashes = {r.get("metadata", {}).get("content_hash") for r in existing}
        new_docs = []
        new_meta = []
        new_ids = []
        for i, h in enumerate([m["content_hash"] for m in metadatas]):
            if h not in existing_hashes:
                new_docs.append(documents[i])
                new_meta.append(metadatas[i])
                new_ids.append(ids[i])

        if not new_docs:
            return {"status": "skipped", "message": "Content already indexed.", "chunks": len(chunks)}

        self.add_documents(client_id, new_docs, new_meta, new_ids)
        return {"status": "success", "chunks": len(new_docs), "total_chunks": len(chunks), "skipped": len(chunks) - len(new_docs)}

    def retrieve(self, client_id: int, query: str, n_results: int = 3) -> Dict[str, Any]:
        results = self.search_knowledge(client_id, query, n_results=n_results)
        if not results:
            return {"results": [], "confidence": 0.0, "message": "No relevant documents found."}
        scores = [1.0 / (1.0 + r.get("score", 1.0)) for r in results]
        avg_conf = sum(scores) / len(scores) if scores else 0.0
        return {"results": results, "confidence": round(avg_conf, 3), "message": ""}

    def should_escalate(self, confidence: float) -> bool:
        return confidence < 0.3

    def auto_reindex(self, client_id: int, directory: str = None) -> Dict[str, Any]:
        scan_dir = directory or UPLOADS_DIR
        if not os.path.isdir(scan_dir):
            return {"status": "error", "message": f"Directory not found: {scan_dir}"}
        ingested = []
        skipped = []
        for fname in os.listdir(scan_dir):
            fpath = os.path.join(scan_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".txt", ".md", ".csv", ".json"):
                continue
            import asyncio
            try:
                result = asyncio.get_event_loop().run_until_complete(
                    self.ingest_document(client_id, fpath)
                )
                if result.get("status") == "success":
                    ingested.append(fname)
                else:
                    skipped.append(fname)
            except Exception as e:
                logger.error("Auto-reindex error for %s: %s", fname, e)
                skipped.append(fname)
        return {"status": "completed", "ingested": ingested, "skipped": skipped}


# Global singleton
rag_pipeline = RAGPipeline()
