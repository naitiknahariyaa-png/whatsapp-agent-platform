"""
ChromaDB conversation memory - semantic search over chat history
"""
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from datetime import datetime
from typing import List, Dict, Optional
import uuid


class ConversationMemory:
    def __init__(self, persist_directory: str = "./chroma_data"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(
            name="conversations",
            metadata={"hnsw:space": "cosine"}
        )
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
    
    def add_message(self, phone_number: str, message: str, role: str = "user"):
        """Add a message to vector store"""
        embedding = self.encoder.encode(message).tolist()
        self.collection.add(
            documents=[message],
            embeddings=[embedding],
            metadatas=[{
                "phone_number": phone_number,
                "role": role,
                "timestamp": datetime.utcnow().isoformat()
            }],
            ids=[str(uuid.uuid4())]
        )
    
    def search_similar(self, phone_number: str, query: str, n_results: int = 3) -> List[Dict]:
        """Search for similar past messages"""
        query_embedding = self.encoder.encode(query).tolist()
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"phone_number": phone_number}
        )
        
        similar = []
        if results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                similar.append({
                    "message": doc,
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i] if results['distances'] else 0
                })
        return similar
    
    def get_context_string(self, phone_number: str, current_message: str) -> str:
        """Get formatted context string for LLM prompt"""
        similar = self.search_similar(phone_number, current_message)
        if not similar:
            return ""
        
        context_parts = ["Previous relevant conversations:"]
        for item in similar:
            role = item['metadata'].get('role', 'user')
            context_parts.append(f"{role}: {item['message']}")
        
        return "\n".join(context_parts)


# Global instance
memory = ConversationMemory()