import logging
import json
from typing import List, Dict, Any, Optional
from vector_store import vector_store
from llm_setup import get_llm

logger = logging.getLogger(\"knowledge_tools\")

async def search_knowledge_base(query: str, client_id: int):
    \"\"\"
    PRODUCTION RAG: Hybrid Search -> Reranking -> Citations.
    \"\"\"
    try:
        # 1. Hybrid Retrieval (get top 20 candidates)
        candidates = await vector_store.hybrid_search(query, client_id, top_k=20)
        if not candidates:
            return \"No relevant information found in the company library.\"

        # 2. Reranking (LLM-based)
        # We ask the LLM to pick the most relevant top 3 from the 20 candidates
        llm = get_llm()
        rerank_prompt = (
            f\"User Query: {query}\\n\\n\"
            \"Candidates:\\n\" + \"\\n\".join([f\"ID {i}: {c['content'][:200]}...\" for i, c in enumerate(candidates)]) + \"\\n\\n\"
            \"Identify the top 3 most relevant IDs. Respond ONLY as a JSON list: [0, 1, 2]\"
        )
        
        rerank_res = await llm.ainvoke([{\"role\": \"user\", \"content\": rerank_prompt}])
        rerank_text = rerank_res.content if hasattr(rerank_res, 'content') else str(rerank_res)
        
        import re
        match = re.search(r'\\[.*\\]', rerank_text)
        if match:
            try:
                top_ids = json.loads(match.group(0))
                # Use reranked results
                final_results = [candidates[i] for i in top_ids if i < len(candidates)]
            except:
                final_results = candidates[:3]
        else:
            final_results = candidates[:3]

        # 3. Grounded Answer + Citation
        # We return a structured string that forces the SupportAgent to cite
        context_blocks = []
        for r in final_results:
            meta = r['metadata']
            source = meta.get('source', 'Unknown Doc')
            content = r['content']
            context_blocks.append(f\"[Source: {source}] {content}\")

        return \"\\n\\n\".join(context_blocks)
    except Exception as e:
        logger.error(f\"Deep RAG Error: {e}\")
        return \"The knowledge base is currently unavailable.\"

async def ingest_document(client_id: int, source: str, source_type: str):
    from ingestor import ingestor
    return await ingestor.ingest(client_id, source, source_type)

from tools.dispatcher import tool_dispatcher
tool_dispatcher.register(\"search_knowledge_base\", search_knowledge_base)
tool_dispatcher.register(\"ingest_document\", ingest_document)
