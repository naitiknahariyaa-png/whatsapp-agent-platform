"""
Vector Store - ChromaDB for semantic search and knowledge base
"""
import os
import json
import uuid
from typing import List, Dict, Optional, Any
from datetime import datetime

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    print("[!] ChromaDB not installed. Run: pip install chromadb")

from config import settings

# Initialize ChromaDB client
if CHROMA_AVAILABLE:
    client = chromadb.PersistentClient(
        path=os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"),
        settings=ChromaSettings(anonymized_telemetry=False)
    )
else:
    client = None


def get_collection(client_id: int, collection_name: str = "knowledge"):
    """Get or create a ChromaDB collection for a specific client."""
    if not client:
        return None
    collection_id = f"{collection_name}_{client_id}"
    try:
        return client.get_collection(collection_id)
    except Exception:
        return client.create_collection(collection_id, metadata={"client_id": client_id})


def add_documents(client_id: int, documents: List[str], metadatas: List[Dict] = None, ids: List[str] = None):
    """Add documents to the vector store for semantic search."""
    if not client:
        return []
    collection = get_collection(client_id)
    if not collection or not documents:
        return []
    
    if ids is None:
        ids = [str(uuid.uuid4()) for _ in documents]
    
    if metadatas is None:
        metadatas = [{"client_id": client_id, "created_at": datetime.utcnow().isoformat()} for _ in documents]
    
    try:
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        return ids
    except Exception as e:
        print(f"[!] Vector store add error: {e}")
        return []


def search_documents(client_id: int, query: str, n_results: int = 5) -> List[Dict]:
    """Semantic search in the vector store."""
    if not client:
        return []
    collection = get_collection(client_id)
    if not collection:
        return []
    
    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, 10)
        )
        
        formatted = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                formatted.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "score": results["distances"][0][i] if results.get("distances") else 0
                })
        return formatted
    except Exception as e:
        print(f"[!] Vector store search error: {e}")
        return []


def delete_documents(client_id: int, ids: List[str]):
    """Delete documents from vector store."""
    if not client:
        return
    collection = get_collection(client_id)
    if not collection:
        return
    
    try:
        collection.delete(ids=ids)
    except Exception as e:
        print(f"[!] Vector store delete error: {e}")


def get_collection_stats(client_id: int) -> Dict:
    """Get statistics about the vector store."""
    if not client:
        return {"available": False}
    
    try:
        collection = get_collection(client_id)
        if not collection:
            return {"available": True, "count": 0}
        
        count = collection.count()
        return {"available": True, "count": count}
    except Exception as e:
        return {"available": False, "error": str(e)}


# Knowledge base helpers
def add_knowledge_item(client_id: int, title: str, content: str, category: str = "general", tags: List[str] = None):
    """Add a knowledge base item with semantic search."""
    documents = [f"Title: {title}\n\n{content}"]
    metadatas = [{
        "client_id": client_id,
        "title": title,
        "category": category,
        "tags": json.dumps(tags or []),
        "created_at": datetime.utcnow().isoformat()
    }]
    return add_documents(client_id, documents, metadatas)


def search_knowledge(client_id: int, query: str, category: str = None) -> List[Dict]:
    """Search knowledge base with optional category filter."""
    results = search_documents(client_id, query, n_results=5)
    
    if category and results:
        filtered = [r for r in results if r.get("metadata", {}).get("category") == category]
        return filtered if filtered else results
    
    return results