"""
Phase 4: AI Power-Ups — Voice, Vision, Language, Sentiment, Knowledge Base
"""
import json
import logging
import os
import tempfile
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from enum import Enum
from io import BytesIO

logger = logging.getLogger("ai_powerups")


# ---------------------------------------------------------------------------
# 1. Voice Note Support (Whisper STT + TTS)
# ---------------------------------------------------------------------------

class VoiceProcessor:
    """Speech-to-Text (Whisper) + Text-to-Speech"""

    def __init__(self, model: str = "whisper-1", tts_voice: str = "alloy"):
        self.model = model
        self.tts_voice = tts_voice
        self._whisper_available = False
        self._tts_available = False

        # Check OpenAI availability
        try:
            from openai import OpenAI
            self._openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
            self._whisper_available = bool(os.getenv("OPENAI_API_KEY"))
            self._tts_available = bool(os.getenv("OPENAI_API_KEY"))
        except ImportError:
            logger.warning("openai not installed. Voice features disabled.")
            self._openai = None

        # Check local whisper (faster, no API cost)
        try:
            import whisper
            self._local_whisper = whisper.load_model("base")
            self._whisper_available = True
            logger.info("[v] Local Whisper model loaded")
        except ImportError:
            self._local_whisper = None
        except Exception:
            self._local_whisper = None

    async def transcribe(self, audio_data: bytes, filename: str = "audio.mp3") -> Optional[str]:
        """Transcribe audio to text using Whisper"""
        if not self._whisper_available:
            return None

        # Try local whisper first (faster, free)
        if self._local_whisper:
            try:
                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio_data)
                    tmp_path = tmp.name

                result = self._local_whisper.transcribe(tmp_path)
                os.unlink(tmp_path)
                return result["text"].strip()
            except Exception as e:
                logger.error(f"Local whisper failed: {e}")

        # Fallback to OpenAI Whisper API
        try:
            import asyncio
            response = await asyncio.to_thread(
                self._openai.audio.transcriptions.create,
                model=self.model,
                file=(filename, BytesIO(audio_data)),
                language="hi",  # Support Hindi
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"OpenAI Whisper failed: {e}")
            return None

    async def synthesize(self, text: str, language: str = "hi") -> Optional[bytes]:
        """Convert text to speech audio"""
        if not self._tts_available:
            return None

        try:
            import asyncio
            response = await asyncio.to_thread(
                self._openai.audio.speech.create,
                model="tts-1",
                voice=self.tts_voice,
                input=text,
            )
            return response.content
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            return None

    async def transcribe_whatsapp_voice(self, media_url: str) -> Optional[str]:
        """Download and transcribe a WhatsApp voice note from media URL"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(media_url)
                if resp.status_code == 200:
                    return await self.transcribe(resp.content)
        except Exception as e:
            logger.error(f"WhatsApp voice download failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 2. Image Understanding (Vision API)
# ---------------------------------------------------------------------------

class ImageAnalyzer:
    """Analyze images — read menus, prescriptions, screenshots, documents"""

    def __init__(self):
        self._available = False
        try:
            from openai import OpenAI
            self._openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
            self._available = bool(os.getenv("OPENAI_API_KEY"))
        except ImportError:
            self._openai = None

    async def analyze(self, image_data: bytes, prompt: str = "Describe this image") -> Optional[str]:
        """Analyze an image using GPT-4 Vision"""
        if not self._available:
            return None

        try:
            import base64
            b64 = base64.b64encode(image_data).decode("utf-8")

            import asyncio
            response = await asyncio.to_thread(
                self._openai.chat.completions.create,
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high"
                        }},
                    ],
                }],
                max_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return None

    async def read_prescription(self, image_data: bytes) -> Optional[Dict]:
        """Specialized: read doctor prescription from image"""
        prompt = """You are a medical prescription reader. Extract the following from this prescription image:
1. Doctor name and clinic
2. Patient name
3. Date
4. Medicine names and dosages
5. Duration
6. Any special instructions

Return as JSON with keys: doctor_name, patient_name, date, medicines (array of {name, dosage, duration}), instructions"""
        result = await self.analyze(image_data, prompt)
        if result:
            try:
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(0))
            except Exception:
                pass
            return {"raw_text": result}
        return None

    async def read_menu(self, image_data: bytes) -> Optional[Dict]:
        """Specialized: read restaurant menu from image"""
        prompt = """You are a menu reader. Extract all menu items from this image.
Return as JSON with structure: {categories: [{name: string, items: [{name: string, price: string, description: string}]}]}"""
        result = await self.analyze(image_data, prompt)
        if result:
            try:
                import re
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(0))
            except Exception:
                pass
            return {"raw_text": result}
        return None

    async def read_document(self, image_data: bytes) -> Optional[str]:
        """Generic document text extraction from image"""
        return await self.analyze(image_data, "Extract all text from this document image clearly.")


# ---------------------------------------------------------------------------
# 3. Multi-language Detection + Translation
# ---------------------------------------------------------------------------

class LanguageDetector:
    """Detect language and translate if needed"""

    LANGUAGES = {
        "hi": "Hindi", "en": "English", "bn": "Bengali", "te": "Telugu",
        "mr": "Marathi", "ta": "Tamil", "ur": "Urdu", "gu": "Gujarati",
        "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "or": "Odia",
    }

    def __init__(self):
        try:
            from langdetect import detect
            self._detect = detect
            self._available = True
        except ImportError:
            self._available = False
            self._detect = None

        try:
            from deep_translator import GoogleTranslator
            self._translator_class = GoogleTranslator
            self._translate_available = True
        except ImportError:
            self._translate_available = False
            self._translator_class = None

    def detect(self, text: str) -> Tuple[str, float]:
        """Detect language, returns (code, confidence)"""
        if not self._available:
            # Fallback: check for devanagari characters
            devanagari = bool(re.search(r'[\u0900-\u097F]', text))
            return ("hi" if devanagari else "en", 0.5)

        try:
            lang = self._detect(text)
            # Map to our supported languages
            if lang in self.LANGUAGES:
                return (lang, 0.9)
            return ("en", 0.7)  # Default to English
        except Exception:
            return ("en", 0.5)

    def translate_to_english(self, text: str) -> Optional[str]:
        """Translate non-English text to English"""
        lang, _ = self.detect(text)
        if lang == "en":
            return text
        if self._translate_available:
            try:
                translator = self._translator_class(source='auto', target='en')
                return translator.translate(text)
            except Exception as e:
                logger.error(f"Translation failed: {e}")
        return text

    def translate_to_language(self, text: str, target_lang: str) -> Optional[str]:
        """Translate English text to target language"""
        if target_lang == "en":
            return text
        if self._translate_available:
            try:
                translator = self._translator_class(source='en', target=target_lang)
                return translator.translate(text)
            except Exception as e:
                logger.error(f"Translation to {target_lang} failed: {e}")
        return text

    def get_language_name(self, code: str) -> str:
        return self.LANGUAGES.get(code, "Unknown")


# ---------------------------------------------------------------------------
# 4. Sentiment Analysis + Auto-escalation
# ---------------------------------------------------------------------------

class SentimentAnalyzer:
    """Analyze sentiment and trigger escalation if needed"""

    def __init__(self, escalation_threshold: float = -0.3):
        self.escalation_threshold = escalation_threshold
        self._available = False
        try:
            from textblob import TextBlob
            self._textblob = TextBlob
            self._available = True
        except ImportError:
            self._textblob = None

    def analyze(self, text: str) -> Dict:
        """Analyze sentiment of a message"""
        result = {
            "text": text[:100],
            "sentiment": "neutral",
            "polarity": 0.0,
            "subjectivity": 0.0,
            "needs_escalation": False,
            "emotion": "neutral",
        }

        if self._available:
            try:
                blob = self._textblob(text)
                polarity = blob.sentiment.polarity  # -1 to 1
                subjectivity = blob.sentiment.subjectivity  # 0 to 1

                result["polarity"] = round(polarity, 2)
                result["subjectivity"] = round(subjectivity, 2)

                # Classify sentiment
                if polarity > 0.3:
                    result["sentiment"] = "positive"
                    result["emotion"] = "happy"
                elif polarity < -0.3:
                    result["sentiment"] = "negative"
                    result["emotion"] = "angry" if polarity < -0.6 else "frustrated"
                else:
                    result["sentiment"] = "neutral"

                # Auto-escalation check
                result["needs_escalation"] = polarity < self.escalation_threshold

                # Check for escalation keywords
                escalation_keywords = [
                    "complaint", "refund", "cancel", "manager", "lawsuit",
                    "lawyer", "police", "cheated", "fraud", "scam",
                    "shikayat", "vaapis", "manejar", "legal",
                ]
                for kw in escalation_keywords:
                    if kw in text.lower():
                        result["needs_escalation"] = True
                        result["emotion"] = "escalated"
                        break

            except Exception as e:
                logger.error(f"Sentiment analysis failed: {e}")

        return result

    def analyze_conversation(self, messages: List[str]) -> Dict:
        """Analyze sentiment trend across multiple messages"""
        if not messages:
            return {}

        results = [self.analyze(m) for m in messages]
        polarities = [r["polarity"] for r in results]

        trend = "stable"
        if len(polarities) >= 3:
            if polarities[-1] < polarities[0] - 0.3:
                trend = "declining"
            elif polarities[-1] > polarities[0] + 0.3:
                trend = "improving"

        return {
            "overall_sentiment": "positive" if sum(polarities) / len(polarities) > 0.1 else "negative" if sum(polarities) / len(polarities) < -0.1 else "neutral",
            "avg_polarity": round(sum(polarities) / len(polarities), 2),
            "trend": trend,
            "needs_escalation": any(r["needs_escalation"] for r in results),
        }


# ---------------------------------------------------------------------------
# 5. Knowledge Base (RAG with vector search)
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """
    Upload docs → chunk → embed → store in Qdrant/Chroma
    Query: embed query → search → LLM summary
    """

    def __init__(self, collection_name: str = "knowledge_base"):
        self.collection_name = collection_name
        self._available = False
        self._vector_client = None
        self._embedding_func = None

    async def initialize(self):
        """Initialize vector DB client"""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import Distance, VectorParams
            import os

            qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
            self._vector_client = QdrantClient(url=qdrant_url)
            self._available = True

            # Create collection if not exists
            collections = self._vector_client.get_collections()
            if self.collection_name not in [c.name for c in collections.collections]:
                self._vector_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                )
            logger.info(f"[v] Knowledge base initialized: {self.collection_name}")
        except ImportError:
            logger.warning("qdrant-client not installed. Install with: pip install qdrant-client")
        except Exception as e:
            logger.warning(f"Vector DB not available: {e}")

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding via OpenAI"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return None

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i:i + chunk_size])
            if chunk:
                chunks.append(chunk)
        return chunks

    async def add_document(self, doc_id: str, text: str, metadata: Optional[Dict] = None):
        """Add a document to the knowledge base"""
        if not self._available or not self._vector_client:
            return False

        try:
            chunks = self._chunk_text(text)
            from qdrant_client.http.models import PointStruct

            points = []
            for i, chunk in enumerate(chunks):
                embedding = self._get_embedding(chunk)
                if embedding:
                    points.append(PointStruct(
                        id=f"{doc_id}_{i}",
                        vector=embedding,
                        payload={
                            "doc_id": doc_id,
                            "chunk_index": i,
                            "text": chunk,
                            "metadata": metadata or {},
                        },
                    ))

            if points:
                self._vector_client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )
                logger.info(f"[v] Added {len(points)} chunks from doc {doc_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to add document: {e}")
        return False

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Search the knowledge base"""
        if not self._available:
            return []

        embedding = self._get_embedding(query)
        if not embedding:
            return []

        try:
            results = self._vector_client.search(
                collection_name=self.collection_name,
                query_vector=embedding,
                limit=limit,
            )
            return [
                {
                    "text": r.payload.get("text", ""),
                    "score": r.score,
                    "doc_id": r.payload.get("doc_id", ""),
                    "metadata": r.payload.get("metadata", {}),
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def delete_document(self, doc_id: str):
        """Delete a document from the knowledge base"""
        if not self._available:
            return
        try:
            from qdrant_client.http.models import Filter, FilterSelector
            self._vector_client.delete(
                collection_name=self.collection_name,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[{"key": "doc_id", "match": {"value": doc_id}}]
                    )
                ),
            )
        except Exception as e:
            logger.error(f"Delete failed: {e}")


# ---------------------------------------------------------------------------
# 6. Conversation Replay & Training Data Export
# ---------------------------------------------------------------------------

class ConversationExporter:
    """Export conversations for training, review, or compliance"""

    EXPORT_FORMATS = ["json", "csv", "jsonl"]

    def __init__(self):
        self._export_path = os.path.join(os.getcwd(), "exports")
        os.makedirs(self._export_path, exist_ok=True)

    async def export_conversation(self, messages: List[Dict], format: str = "json",
                                   filename: Optional[str] = None) -> Optional[str]:
        """Export a conversation in specified format"""
        if format not in self.EXPORT_FORMATS:
            logger.error(f"Unsupported format: {format}")
            return None

        if not filename:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"conversation_{timestamp}.{format}"

        filepath = os.path.join(self._export_path, filename)

        try:
            if format == "json":
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(messages, f, indent=2, ensure_ascii=False)

            elif format == "jsonl":
                with open(filepath, "w", encoding="utf-8") as f:
                    for msg in messages:
                        f.write(json.dumps(msg, ensure_ascii=False) + "\n")

            elif format == "csv":
                import csv
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    if messages:
                        writer = csv.DictWriter(f, fieldnames=messages[0].keys())
                        writer.writeheader()
                        writer.writerows(messages)

            logger.info(f"[v] Conversation exported: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return None

    def export_training_data(self, conversations: List[List[Dict]],
                              output_format: str = "jsonl") -> Optional[str]:
        """Export conversations as training data (prompt-response pairs)"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self._export_path, f"training_data_{timestamp}.{output_format}")

        training_pairs = []
        for conv in conversations:
            for i in range(0, len(conv) - 1, 2):
                if i + 1 < len(conv):
                    training_pairs.append({
                        "messages": [
                            {"role": "user", "content": conv[i].get("content", "")},
                            {"role": "assistant", "content": conv[i + 1].get("content", "")},
                        ]
                    })

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                if output_format == "jsonl":
                    for pair in training_pairs:
                        f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                else:
                    json.dump(training_pairs, f, indent=2, ensure_ascii=False)

            logger.info(f"[v] Training data exported: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Training export failed: {e}")
            return None


# ---------------------------------------------------------------------------
# 7. Prompt Versioning
# ---------------------------------------------------------------------------

class PromptVersion:
    """A versioned prompt template"""

    def __init__(self, prompt_id: str, content: str, version: int = 1,
                 author: str = "system", metadata: Optional[Dict] = None):
        self.prompt_id = prompt_id
        self.content = content
        self.version = version
        self.author = author
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow().isoformat()
        self.is_active = True

    def to_dict(self) -> Dict:
        return {
            "prompt_id": self.prompt_id,
            "content": self.content,
            "version": self.version,
            "author": self.author,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


class PromptManager:
    """
    Version control for AI prompts.
    - Create new versions without breaking existing
    - A/B test prompts
    - Rollback to previous versions
    """

    def __init__(self):
        self.prompts: Dict[str, List[PromptVersion]] = {}
        self.active_versions: Dict[str, str] = {}  # prompt_id -> version content hash

    def register(self, prompt_id: str, content: str, author: str = "system",
                 metadata: Optional[Dict] = None) -> PromptVersion:
        """Register a new prompt or create a new version"""
        if prompt_id not in self.prompts:
            self.prompts[prompt_id] = []
            version_num = 1
        else:
            version_num = len(self.prompts[prompt_id]) + 1

        prompt = PromptVersion(prompt_id, content, version_num, author, metadata)
        self.prompts[prompt_id].append(prompt)
        self.active_versions[prompt_id] = prompt.content
        logger.info(f"[+] Prompt '{prompt_id}' v{version_num} registered by {author}")
        return prompt

    def get_active(self, prompt_id: str) -> Optional[str]:
        """Get the active version of a prompt"""
        return self.active_versions.get(prompt_id)

    def get_version(self, prompt_id: str, version: int) -> Optional[PromptVersion]:
        """Get a specific version of a prompt"""
        versions = self.prompts.get(prompt_id, [])
        for p in versions:
            if p.version == version:
                return p
        return None

    def rollback(self, prompt_id: str, version: int) -> bool:
        """Rollback to a previous version"""
        prompt = self.get_version(prompt_id, version)
        if prompt:
            self.active_versions[prompt_id] = prompt.content
            logger.info(f"[v] Prompt '{prompt_id}' rolled back to v{version}")
            return True
        return False

    def list_versions(self, prompt_id: str) -> List[Dict]:
        """List all versions of a prompt"""
        return [p.to_dict() for p in self.prompts.get(prompt_id, [])]

    def compare_versions(self, prompt_id: str, v1: int, v2: int) -> Dict:
        """Compare two versions of a prompt"""
        p1 = self.get_version(prompt_id, v1)
        p2 = self.get_version(prompt_id, v2)
        if not p1 or not p2:
            return {"error": "Version not found"}
        return {
            "prompt_id": prompt_id,
            "version_1": {"version": v1, "author": p1.author, "created_at": p1.created_at},
            "version_2": {"version": v2, "author": p2.author, "created_at": p2.created_at},
            "content_diff": self._diff(p1.content, p2.content),
            "length_diff": len(p2.content) - len(p1.content),
        }

    def _diff(self, text1: str, text2: str) -> Dict:
        """Simple diff between two texts"""
        lines1 = text1.splitlines()
        lines2 = text2.splitlines()
        added = [l for l in lines2 if l not in lines1]
        removed = [l for l in lines1 if l not in lines2]
        return {
            "lines_added": len(added),
            "lines_removed": len(removed),
            "samples": {"added": added[:5], "removed": removed[:5]},
        }


# Global instances
voice_processor = VoiceProcessor()
image_analyzer = ImageAnalyzer()
language_detector = LanguageDetector()
sentiment_analyzer = SentimentAnalyzer()
knowledge_base = KnowledgeBase()
conversation_exporter = ConversationExporter()
prompt_manager = PromptManager()