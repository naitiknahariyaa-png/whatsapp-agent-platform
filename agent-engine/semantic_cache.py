"""
Semantic Caching Layer
======================

Caches LLM responses for near-duplicate questions using embedding similarity.
Checks embedding similarity against a cache before hitting the LLM.

Features:
- Embedding-based similarity search (cosine similarity)
- TTL-based expiration
- Per-tenant isolation
- Hit/miss metrics
- Configurable similarity threshold
- Automatic cache warming
"""
import os
import json
import hashlib
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("semantic_cache")

try:
    import redis
    import numpy as np
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis/numpy not available, using in-memory fallback")


@dataclass
class CacheEntry:
    """A single cache entry."""
    key: str
    query: str
    query_hash: str
    embedding: List[float]
    response: str
    task_type: str
    tenant_id: int
    vertical: str
    language: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: Optional[str] = None
    hit_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        return cls(**data)


class SemanticCache:
    """
    Semantic cache using embedding similarity for LLM response caching.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        default_ttl_hours: int = 24,
        max_entries: int = 10000,
        redis_url: str = "redis://localhost:6379/2",
    ):
        self.similarity_threshold = similarity_threshold
        self.default_ttl = timedelta(hours=default_ttl_hours)
        self.max_entries = max_entries
        self.redis_url = redis_url
        self._redis = None
        self._local_cache: Dict[str, CacheEntry] = {}
        self._embedding_cache: Dict[str, List[float]] = {}
        self._stats = {"hits": 0, "misses": 0, "stores": 0, "evictions": 0}
        self._init_redis()

    def _init_redis(self):
        if REDIS_AVAILABLE:
            try:
                self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
                self._redis.ping()
                logger.info("Semantic cache connected to Redis")
            except Exception as e:
                logger.warning("Redis not available, using in-memory cache: %s", e)
                self._redis = None

    # ─── Embedding Generation ──────────────────────────────────────

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text (cached)."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        if text_hash in self._embedding_cache:
            return self._embedding_cache[text_hash]

        # Use a simple hash-based embedding for now
        # In production, use sentence-transformers or OpenAI embeddings
        embedding = self._hash_embedding(text)
        self._embedding_cache[text_hash] = embedding
        return embedding

    def _hash_embedding(self, text: str, dim: int = 384) -> List[float]:
        """Generate a deterministic pseudo-embedding from text hash."""
        # Use multiple hash seeds for better distribution
        embeddings = []
        for i in range(dim):
            seed = f"{text}:{i}"
            h = hashlib.sha256(seed.encode()).hexdigest()
            val = int(h[:8], 16) / 0xFFFFFFFF
            embeddings.append(val * 2 - 1)  # [-1, 1]
        # Normalize
        norm = sum(x * x for x in embeddings) ** 0.5
        if norm > 0:
            embeddings = [x / norm for x in embeddings]
        return embeddings

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ─── Cache Key Generation ──────────────────────────────────────

    def _make_key(self, query: str, task_type: str, tenant_id: int, vertical: str, language: str) -> str:
        """Generate a cache key."""
        components = f"{task_type}:{tenant_id}:{vertical}:{language}:{query}"
        return hashlib.sha256(components.encode()).hexdigest()[:32]

    # ─── Core Operations ───────────────────────────────────────────

    async def get(self, query: str, task_type: str, tenant_id: int,
                  vertical: str = "general", language: str = "en") -> Optional[CacheEntry]:
        """Find a semantically similar cached response."""
        query_embedding = self._get_embedding(query)
        cache_key = self._make_key(query, task_type, tenant_id, vertical, language)

        # Try exact key match first
        entry = await self._get_by_key(cache_key)
        if entry and not self._is_expired(entry):
            if self._is_same_tenant(entry, tenant_id):
                entry.hit_count += 1
                await self._update_entry(entry)
                self._stats["hits"] += 1
                logger.debug("Cache HIT (exact): %s", cache_key[:8])
                return entry

        # Semantic search for similar queries
        similar = await self._find_similar(query_embedding, task_type, tenant_id, vertical, language)
        if similar:
            entry, similarity = similar
            if similarity >= self.similarity_threshold and not self._is_expired(entry):
                if self._is_same_tenant(entry, tenant_id):
                    entry.hit_count += 1
                    await self._update_entry(entry)
                    self._stats["hits"] += 1
                    logger.debug("Cache HIT (semantic, %.2f): %s", similarity, cache_key[:8])
                    return entry

        self._stats["misses"] += 1
        return None

    async def set(
        self,
        query: str,
        response: str,
        task_type: str,
        tenant_id: int,
        vertical: str = "general",
        language: str = "en",
        model_used: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        ttl_hours: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CacheEntry:
        """Store a new cache entry."""
        query_embedding = self._get_embedding(query)
        cache_key = self._make_key(query, task_type, tenant_id, vertical, language)
        ttl = timedelta(hours=ttl_hours) if ttl_hours else self.default_ttl
        expires_at = datetime.utcnow() + ttl

        entry = CacheEntry(
            key=cache_key,
            query=query,
            query_hash=hashlib.sha256(query.encode()).hexdigest()[:16],
            embedding=query_embedding,
            response=response,
            task_type=task_type,
            tenant_id=tenant_id,
            vertical=vertical,
            language=language,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            expires_at=expires_at.isoformat(),
            metadata=metadata or {},
        )

        await self._store_entry(entry)
        self._stats["stores"] += 1
        await self._enforce_max_entries()
        return entry

    # ─── Storage Backend ───────────────────────────────────────────

    async def _get_by_key(self, key: str) -> Optional[CacheEntry]:
        if self._redis:
            try:
                data = self._redis.get(f"semantic_cache:{key}")
                if data:
                    return CacheEntry.from_dict(json.loads(data))
            except Exception as e:
                logger.warning("Redis get failed: %s", e)
        return self._local_cache.get(key)

    async def _store_entry(self, entry: CacheEntry):
        if self._redis:
            try:
                self._redis.setex(
                    f"semantic_cache:{entry.key}",
                    int((datetime.fromisoformat(entry.expires_at) - datetime.utcnow()).total_seconds()),
                    json.dumps(entry.to_dict()),
                )
            except Exception as e:
                logger.warning("Redis set failed: %s", e)
                self._local_cache[entry.key] = entry
        else:
            self._local_cache[entry.key] = entry

    async def _update_entry(self, entry: CacheEntry):
        await self._store_entry(entry)

    async def _find_similar(
        self,
        query_embedding: List[float],
        task_type: str,
        tenant_id: int,
        vertical: str,
        language: str,
    ) -> Optional[Tuple[CacheEntry, float]]:
        """Find the most similar cached entry."""
        candidates = []

        if self._redis:
            # Scan Redis for matching keys (simplified - in production use Redis search)
            try:
                pattern = f"semantic_cache:*{task_type}:{tenant_id}:{vertical}:{language}*"
                keys = self._redis.keys(pattern)
                for key in keys[:100]:  # Limit scan
                    data = self._redis.get(key)
                    if data:
                        entry = CacheEntry.from_dict(json.loads(data))
                        if not self._is_expired(entry):
                            sim = self._cosine_similarity(query_embedding, entry.embedding)
                            if sim >= self.similarity_threshold:
                                candidates.append((entry, sim))
            except Exception as e:
                logger.warning("Redis similarity search failed: %s", e)
        else:
            # In-memory search
            for entry in self._local_cache.values():
                if (entry.task_type == task_type and entry.tenant_id == tenant_id and
                    entry.vertical == vertical and entry.language == language and
                    not self._is_expired(entry)):
                    sim = self._cosine_similarity(query_embedding, entry.embedding)
                    if sim >= self.similarity_threshold:
                        candidates.append((entry, sim))

        if not candidates:
            return None

        # Return best match
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0]

    def _is_expired(self, entry: CacheEntry) -> bool:
        if not entry.expires_at:
            return False
        return datetime.fromisoformat(entry.expires_at) < datetime.utcnow()

    def _is_same_tenant(self, entry: CacheEntry, tenant_id: int) -> bool:
        return entry.tenant_id == tenant_id

    async def _enforce_max_entries(self):
        """Evict oldest entries if over limit."""
        if len(self._local_cache) > self.max_entries:
            # Sort by hit_count + age, evict worst
            sorted_entries = sorted(
                self._local_cache.items(),
                key=lambda x: (x[1].hit_count, x[1].created_at)
            )
            to_evict = len(sorted_entries) - self.max_entries
            for key, _ in sorted_entries[:to_evict]:
                del self._local_cache[key]
                self._stats["evictions"] += 1

    # ─── Stats & Management ────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "local_entries": len(self._local_cache),
            "embedding_cache_size": len(self._embedding_cache),
            "hit_rate": self._stats["hits"] / max(1, self._stats["hits"] + self._stats["misses"]),
        }

    async def invalidate(self, tenant_id: Optional[int] = None, vertical: Optional[str] = None):
        """Invalidate cache entries."""
        if tenant_id is None and vertical is None:
            self._local_cache.clear()
            if self._redis:
                try:
                    self._redis.flushdb()
                except Exception:
                    pass
            return

        keys_to_delete = []
        for key, entry in self._local_cache.items():
            if (tenant_id is None or entry.tenant_id == tenant_id) and \
               (vertical is None or entry.vertical == vertical):
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self._local_cache[key]
            if self._redis:
                try:
                    self._redis.delete(f"semantic_cache:{key}")
                except Exception:
                    pass

    async def warm_cache(self, queries: List[Dict[str, Any]]):
        """Pre-populate cache with common queries."""
        for q in queries:
            # Check if already cached
            existing = await self.get(
                q["query"], q["task_type"], q.get("tenant_id", 1),
                q.get("vertical", "general"), q.get("language", "en")
            )
            if not existing:
                # This would normally call the LLM - for warming, we skip
                logger.info("Cache warming: would cache %s", q["query"][:50])


# ─── Global Instance ──────────────────────────────────────────────

semantic_cache = SemanticCache()


# ─── Integration Helpers ───────────────────────────────────────────

async def cached_llm_call(
    query: str,
    task_type: str,
    llm_call: callable,
    tenant_id: int = 1,
    vertical: str = "general",
    language: str = "en",
    model: str = "",
    **kwargs,
) -> str:
    """
    Wrapper that checks semantic cache before calling LLM.
    """
    # Check cache
    cached = await semantic_cache.get(query, task_type, tenant_id, vertical, language)
    if cached:
        logger.info("Semantic cache HIT for %s (%.0f%% similar)", task_type, cached.hit_count)
        return cached.response

    # Cache miss - call LLM
    response = await llm_call(query, **kwargs)

    # Store in cache
    await semantic_cache.set(
        query=query,
        response=response,
        task_type=task_type,
        tenant_id=tenant_id,
        vertical=vertical,
        language=language,
        model_used=model,
    )

    return response


def get_cache_stats() -> Dict[str, Any]:
    return semantic_cache.get_stats()