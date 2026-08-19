import os
import re
import uuid
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

# Third-party libraries for ingestion
try:
    import fitz  # PyMuPDF for PDFs
    import docx  # python-docx for DOCX
    import requests
    from bs4 import BeautifulSoup
    CHROMA_READY = True
except ImportError:
    CHROMA_READY = False

from vector_store import vector_store

logger = logging.getLogger("ingestor")

class DocumentIngestor:
    \"\"\"
    Production-grade ingestion pipeline:
    Source (PDF/DOCX/URL) -> Clean -> Chunk -> Embed -> Store.
    \"\"\"
    def __init__(self, chunk_size: int = 600, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def _clean_text(self, text: str) -> str:
        \"\"\"Removes noise, boilerplate, and excess whitespace.\"\"\"
        # Remove multiple newlines
        text = re.sub(r'\\n{3,}', '\\n\\n', text)
        # Remove multiple spaces
        text = re.sub(r'[ \\t]+', ' ', text)
        return text.strip()

    def _chunk_text(self, text: str) -> List[str]:
        \"\"\"
        Chunks text into segments of approx 400-800 tokens.
        Since we are using character counts as a proxy for tokens (1 token approx 4 chars),
        we target roughly 1600-3200 characters.
        \"\"\"
        # For production, we'd use a tokenizer (e.g. tiktoken), 
        # but character-based semantic splitting is a robust fallback.
        char_limit = self.chunk_size * 4 
        overlap_limit = self.overlap * 4
        
        chunks = []
        start = 0
        while start < len(text):
            end = start + char_limit
            chunk = text[start:end]
            
            # Try to split at the nearest sentence end
            if end < len(text):
                last_period = chunk.rfind('. ')
                if last_period > char_limit // 2:
                    chunk = chunk[:last_period + 1]
                    end = start + len(chunk)
            
            chunks.append(chunk)
            start = end - overlap_limit
        return chunks

    def extract_from_pdf(self, file_path: str) -> str:
        \"\"\"Extract text from PDF using PyMuPDF.\"\"\"
        text = \"\"\"
        try:
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text() + \"\\n\"
            doc.close()
        except Exception as e:
            logger.error(f\"PDF extraction failed for {file_path}: {e}\")
        return text

    def extract_from_docx(self, file_path: str) -> str:
        \"\"\"Extract text from DOCX using python-docx.\"\"\"
        text = \"\"\"
        try:
            doc = docx.Document(file_path)
            text = \"\\n\".join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.error(f\"DOCX extraction failed for {file_path}: {e}\")
        return text

    def extract_from_url(self, url: str) -> str:
        \"\"\"Extract clean text from a URL using BeautifulSoup.\"\"\"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script and style elements
            for script or style in soup(["script", \"style\", \"nav\", \"footer\", \"header\"]):
                script.decompose()
                
            return soup.get_text(separator=\"\\n\")
        except Exception as e:
            logger.error(f\"URL extraction failed for {url}: {e}\")
            return \"\"

    async def ingest(self, client_id: int, source: str, source_type: str) -> Dict[str, Any]:
        \"\"\"
        Main ingestion pipeline.
        source_type: 'pdf', 'docx', 'url', 'text'
        \"\"\"
        logger.info(f\"Ingesting {source_type} for client {client_id}: {source}\")
        
        # 1. Extraction
        if source_type == 'pdf':
            raw_text = self.extract_from_pdf(source)
        elif source_type == 'docx':
            raw_text = self.extract_from_docx(source)
        elif source_type == 'url':
            raw_text = self.extract_from_url(source)
        else:
            with open(source, 'r', encoding='utf-8') as f:
                raw_text = f.read()

        if not raw_text or len(raw_text.strip()) == 0:
            return {\"status\": \"error\", \"message\": \"No text extracted from source.\"}

        # 2. Cleaning
        cleaned_text = self._clean_text(raw_text)

        # 3. Chunking
        chunks = self._chunk_text(cleaned_text)
        
        # 4. Embedding & Storage
        doc_id = str(uuid.uuid4())
        
        # we pass metadata to vector_store to be tagged
        metadata = {
            \"client_id\": client_id,
            \"doc_id\": doc_id,
            \"source\": source,
            \"source_type\": source_type,
            \"ingested_at\": datetime.now(timezone.utc).isoformat()
        }

        # Use vector_store's upgraded add_documents method
        ids = vector_store.add_documents(
            client_id=client_id, 
            text=cleaned_text, # VectorStore handles internal chunking based on updated code
            metadata=metadata
        )

        return {
            \"status\": \"success\", 
            \"doc_id\": doc_id, 
            \"chunks_created\": len(ids), 
            \"source\": source
        }

# Singleton instance
ingestor = DocumentIngestor()
