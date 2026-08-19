from config import settings


class SellerLLMService:
    def __init__(self):
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.api_key = settings.groq_api_key
        self.ollama_url = settings.ollama_base_url

    async def generate_seo_suggestions(self, listing_title: str, bullets: str, description: str, keywords: str) -> str:
        prompt = f"""You are an Amazon/Flipkart SEO expert. Optimize the following listing for search visibility and conversion.

Current title: {listing_title}
Current bullets: {bullets}
Current description: {description}
Target keywords: {keywords}

Rules:
- Title must be under 200 characters
- Include top 2-3 keywords naturally
- Bullets should highlight benefits, not just features
- Avoid banned/promotional words
- Keep tone factual and professional

Return optimized title, bullets (5 max), and description:"""

        if self.provider == "groq" and self.api_key:
            return await self._call_groq(prompt)
        elif self.provider == "ollama":
            return await self._call_ollama(prompt)
        else:
            return "[LLM] No provider configured. Set GROQ_API_KEY or OLLAMA_BASE_URL."

    async def generate_price_insight(self, product_name: str, my_price: float, competitor_prices: list) -> str:
        prompt = f"""You are an e-commerce pricing analyst. Analyze the following price data and suggest whether to raise, lower, or hold price.

Product: {product_name}
My price: {my_price}
Competitor prices: {competitor_prices}

Return a concise recommendation (max 50 words):"""

        if self.provider == "groq" and self.api_key:
            return await self._call_groq(prompt)
        elif self.provider == "ollama":
            return await self._call_ollama(prompt)
        else:
            return "[LLM] No provider configured."

    async def _call_groq(self, prompt: str) -> str:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 1024,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[Groq Error] {str(e)}"

    async def _call_ollama(self, prompt: str) -> str:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "")
        except Exception as e:
            return f"[Ollama Error] {str(e)}"
