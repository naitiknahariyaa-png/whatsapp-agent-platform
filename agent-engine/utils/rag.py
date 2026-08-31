"""
RAG / Knowledge Functions
The difference between helpful answers and confident hallucinations.
"""
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# 4.1 hash_document — Avoid re-embedding unchanged files
# =============================================================================
def hash_document(file_bytes: bytes, algorithm: str = "sha256") -> str:
    """
    Content hash to detect if a re-uploaded doc actually changed.
    Avoids re-embedding (and paying for) unchanged files.
    
    Args:
        file_bytes: Raw file content
        algorithm: Hash algorithm (sha256, md5, sha1)
    
    Returns:
        Hex digest of the content hash
    """
    if algorithm == "sha256":
        return hashlib.sha256(file_bytes).hexdigest()
    elif algorithm == "md5":
        return hashlib.md5(file_bytes).hexdigest()
    elif algorithm == "sha1":
        return hashlib.sha1(file_bytes).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")


def hash_text(text: str, algorithm: str = "sha256") -> str:
    """Hash a text string for deduplication."""
    return hash_document(text.encode('utf-8'), algorithm)


# =============================================================================
# 4.2 chunk_with_overlap — Better retrieval through overlap
# =============================================================================
def chunk_with_overlap(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    separators: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Splits documents for embedding with overlap.
    Overlap alone measurably improves retrieval quality vs naive splitting.
    
    Args:
        text: Document text to chunk
        chunk_size: Target size per chunk (characters)
        overlap: Overlap between chunks (characters)
        separators: Preferred split points (default: paragraphs, sentences)
    
    Returns:
        List of chunks with metadata: {"content": str, "start": int, "end": int, "index": int}
    """
    if separators is None:
        separators = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]
    
    if len(text) <= chunk_size:
        return [{"content": text, "start": 0, "end": len(text), "index": 0}]
    
    chunks = []
    start = 0
    chunk_index = 0
    
    while start < len(text):
        # Find end position
        end = min(start + chunk_size, len(text))
        
        # Try to find a good separator near the end
        if end < len(text):
            best_sep_pos = -1
            for sep in separators:
                # Search backwards from end
                pos = text.rfind(sep, start, end)
                if pos > best_sep_pos:
                    best_sep_pos = pos
            
            if best_sep_pos > start:
                end = best_sep_pos + len(separators[0])  # Include separator
        
        chunk_content = text[start:end].strip()
        if chunk_content:
            chunks.append({
                "content": chunk_content,
                "start": start,
                "end": end,
                "index": chunk_index,
            })
            chunk_index += 1
        
        # Move start with overlap
        new_start = end - overlap
        if new_start <= start:
            new_start = end  # Prevent infinite loop
        start = new_start
    
    return chunks


# =============================================================================
# 4.3 confidence_threshold_check — The #1 hallucination preventer
# =============================================================================
@dataclass
class RetrievalResult:
    """Result of a retrieval operation with confidence."""
    content: str
    score: float  # 0-1, higher = more relevant
    metadata: Dict[str, Any]
    source: str


def confidence_threshold_check(
    results: List[RetrievalResult],
    threshold: float = 0.7,
    min_results: int = 1,
) -> Tuple[bool, List[RetrievalResult]]:
    """
    Decides "answer" vs "say I don't know".
    Directly prevents hallucinated answers — arguably the single highest-leverage function in the whole RAG stack.
    
    Args:
        results: List of retrieval results with scores
        threshold: Minimum similarity score (0-1, higher = stricter)
        min_results: Minimum number of results above threshold
    
    Returns:
        (should_answer, filtered_results)
        - should_answer: True if we have enough confident results
        - filtered_results: Results meeting threshold
    """
    if not results:
        return False, []
    
    # Filter by threshold
    confident = [r for r in results if r.score >= threshold]
    
    should_answer = len(confident) >= min_results
    
    if not should_answer:
        logger.debug(f"RAG confidence check failed: {len(confident)}/{min_results} results above {threshold}")
    
    return should_answer, confident


def adaptive_confidence_threshold(
    results: List[RetrievalResult],
    base_threshold: float = 0.7,
    query_complexity: str = "normal",  # "simple", "normal", "complex"
) -> float:
    """
    Adjust threshold based on query complexity.
    Simple queries need lower threshold, complex need higher.
    """
    adjustments = {
        "simple": -0.1,
        "normal": 0.0,
        "complex": 0.1,
    }
    return base_threshold + adjustments.get(query_complexity, 0.0)


# =============================================================================
# 4.4 cite_source — Builds trust & enables debugging
# =============================================================================
def cite_source(
    chunk_metadata: Dict[str, Any],
    format_style: str = "bracket",
) -> str:
    """
    Attaches doc name/section to an answer.
    Builds trust, and makes debugging wrong answers trivial.
    
    Args:
        chunk_metadata: Metadata from retrieved chunk (title, source, page, etc.)
        format_style: "bracket", "inline", "footnote", "markdown"
    
    Returns:
        Formatted citation string
    """
    title = chunk_metadata.get("title", "Unknown Source")
    source = chunk_metadata.get("source", "")
    page = chunk_metadata.get("page")
    section = chunk_metadata.get("section")
    url = chunk_metadata.get("url")
    
    parts = [title]
    if section:
        parts.append(f"§{section}")
    if page:
        parts.append(f"p.{page}")
    if source:
        parts.append(source)
    
    citation = " | ".join(parts)
    
    if format_style == "bracket":
        return f"[{citation}]"
    elif format_style == "inline":
        return f"(Source: {citation})"
    elif format_style == "footnote":
        return f"¹{citation}"
    elif format_style == "markdown":
        if url:
            return f"[{citation}]({url})"
        return f"**{citation}**"
    else:
        return citation


def format_answer_with_citations(
    answer: str,
    citations: List[str],
    style: str = "numbered",
) -> str:
    """
    Append citations to an answer in a clean format.
    """
    if not citations:
        return answer
    
    if style == "numbered":
        citation_text = "\n\nSources:\n" + "\n".join(
            f"{i+1}. {c}" for i, c in enumerate(citations)
        )
    elif style == "inline":
        citation_text = " " + " ".join(f"[{i+1}]" for i in range(len(citations)))
    else:
        citation_text = "\n\nSources: " + "; ".join(citations)
    
    return answer.rstrip() + citation_text


# =============================================================================
# 4.5 rerank_top_k — Cheap accuracy boost
# =============================================================================
async def rerank_top_k(
    query: str,
    candidates: List[RetrievalResult],
    top_k: int = 5,
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> List[RetrievalResult]:
    """
    Cheap reorder pass on top ~20 retrieved chunks.
    Cheap to add, disproportionate accuracy gain.
    
    Args:
        query: Original user query
        candidates: Initial retrieval results
        top_k: How many to return after reranking
        model_name: Cross-encoder model to use
    
    Returns:
        Reranked results
    """
    if not candidates:
        return []
    
    if len(candidates) <= top_k:
        return candidates
    
    # Try to use a cross-encoder for reranking
    try:
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(model_name)
        
        # Prepare pairs
        pairs = [(query, c.content[:512]) for c in candidates]
        
        # Score in batches
        scores = reranker.predict(pairs, batch_size=16)
        
        # Attach scores and sort
        for candidate, score in zip(candidates, scores):
            candidate.rerank_score = float(score)
        
        candidates.sort(key=lambda x: x.rerank_score, reverse=True)
        logger.debug(f"Reranked {len(candidates)} candidates, returning top {top_k}")
        
    except ImportError:
        logger.warning("sentence-transformers not installed, skipping reranking")
    except Exception as e:
        logger.warning(f"Reranking failed: {e}")
    
    return candidates[:top_k]


def mmr_rerank(
    query: str,
    candidates: List[RetrievalResult],
    top_k: int = 5,
    lambda_param: float = 0.5,
) -> List[RetrievalResult]:
    """
    Maximal Marginal Relevance reranking — balances relevance with diversity.
    Pure Python fallback when cross-encoder unavailable.
    """
    if not candidates:
        return []
    
    if len(candidates) <= top_k:
        return candidates
    
    selected = []
    remaining = candidates.copy()
    
    # First: pick highest scored
    selected.append(max(remaining, key=lambda x: x.score))
    remaining.remove(selected[-1])
    
    # Then: MMR selection
    while len(selected) < top_k and remaining:
        best_score = -1
        best_candidate = None
        
        for candidate in remaining:
            # Relevance score
            relevance = candidate.score
            
            # Diversity: max similarity to already selected
            max_sim = 0
            for sel in selected:
                # Simple Jaccard similarity on words
                c_words = set(candidate.content.lower().split())
                s_words = set(sel.content.lower().split())
                if c_words and s_words:
                    sim = len(c_words & s_words) / len(c_words | s_words)
                    max_sim = max(max_sim, sim)
            
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
            
            if mmr_score > best_score:
                best_score = mmr_score
                best_candidate = candidate
        
        if best_candidate:
            selected.append(best_candidate)
            remaining.remove(best_candidate)
    
    return selected