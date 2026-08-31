"""
External Integrations Utility Functions
Speech-to-text, vision, translation, geocoding, and other integrations.
"""
import logging
import os
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 10.1 whisper_transcribe — Voice message transcription
# ---------------------------------------------------------------------------
async def whisper_transcribe(
    audio_bytes: bytes,
    filename: str = "audio.ogg",
    language: str = "en",
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Transcribe audio using OpenAI Whisper API.

    Args:
        audio_bytes: Raw audio file bytes
        filename: Filename with extension (determines format)
        language: ISO 639-1 language code
        api_key: OpenAI API key

    Returns:
        Transcribed text or None on failure
    """
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OpenAI API key not configured for transcription")
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            files = {"file": (filename, audio_bytes, "audio/ogg")}
            data = {"model": "whisper-1", "language": language}
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                files=files,
                data=data,
                headers=headers,
            )
        if resp.status_code == 200:
            result = resp.json()
            return result.get("text", "")
        logger.error(f"Whisper transcription failed: {resp.text}")
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
    return None


# ---------------------------------------------------------------------------
# 10.2 vision_describe — Image understanding
# ---------------------------------------------------------------------------
async def vision_describe(
    image_bytes: bytes,
    prompt: str = "Describe this image in detail.",
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Describe an image using GPT-4 Vision.

    Args:
        image_bytes: Raw image bytes
        prompt: Description prompt
        api_key: OpenAI API key

    Returns:
        Image description or None on failure
    """
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OpenAI API key not configured for vision")
        return None

    try:
        import base64
        b64_image = base64.b64encode(image_bytes).decode()

        async with httpx.AsyncClient(timeout=30) as client:
            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                            },
                        ],
                    }
                ],
                "max_tokens": 500,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        if resp.status_code == 200:
            result = resp.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content
        logger.error(f"Vision description failed: {resp.text}")
    except Exception as e:
        logger.error(f"Vision description error: {e}")
    return None


# ---------------------------------------------------------------------------
# 10.3 translate_text — Multi-language support
# ---------------------------------------------------------------------------
async def translate_text(
    text: str,
    target_language: str = "en",
    source_language: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Translate text to target language.

    Args:
        text: Text to translate
        target_language: Target language code (e.g., "en", "hi", "es")
        source_language: Source language code (auto-detect if None)
        api_key: OpenAI API key

    Returns:
        Translated text or None on failure
    """
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("API key not configured for translation")
        return None

    lang_names = {
        "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French",
        "ar": "Arabic", "de": "German", "pt": "Portuguese", "zh": "Chinese",
        "ja": "Japanese", "ko": "Korean", "ru": "Russian", "ta": "Tamil",
        "te": "Telugu", "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati",
    }
    target_name = lang_names.get(target_language, target_language)

    source_hint = f" from {lang_names.get(source_language, source_language)}" if source_language else ""

    prompt = f"Translate the following text{source_hint} to {target_name}. Return ONLY the translated text, no explanation:\n\n{text}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        if resp.status_code == 200:
            result = resp.json()
            return result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        logger.error(f"Translation failed: {resp.text}")
    except Exception as e:
        logger.error(f"Translation error: {e}")
    return None


# ---------------------------------------------------------------------------
# 10.4 geocode_address — Maps integration
# ---------------------------------------------------------------------------
async def geocode_address(
    address: str,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Geocode an address using Google Maps Geocoding API.

    Args:
        address: Address string to geocode
        api_key: Google Maps API key

    Returns:
        Dict with lat, lng, formatted_address or None
    """
    api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.warning("Google Maps API key not configured")
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {
                "address": address,
                "key": api_key,
            }
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params=params,
            )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                loc = results[0]["geometry"]["location"]
                return {
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "formatted_address": results[0]["formatted_address"],
                }
        logger.error(f"Geocoding failed: {resp.text}")
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
    return None


# ---------------------------------------------------------------------------
# 10.5 short_url — Link shortener
# ---------------------------------------------------------------------------
async def short_url(
    long_url: str,
    api_key: Optional[str] = None,
    service: str = "bitly",
) -> Optional[str]:
    """
    Shorten a URL for WhatsApp (which prefers short links).

    Args:
        long_url: URL to shorten
        api_key: Shortener API key
        service: "bitly" or "tinyurl"

    Returns:
        Shortened URL or None
    """
    if service == "tinyurl":
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://tinyurl.com/api-create.php",
                    params={"url": long_url},
                )
            if resp.status_code == 200:
                return resp.text.strip()
        except Exception as e:
            logger.error(f"TinyURL error: {e}")

    api_key = api_key or os.getenv("BITLY_API_KEY", "")
    if not api_key or service != "bitly":
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"long_url": long_url}
            resp = await client.post(
                "https://api-ssl.bitly.com/v4/shorten",
                json=payload,
                headers=headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("link")
        logger.error(f"Bitly error: {resp.text}")
    except Exception as e:
        logger.error(f"URL shortening error: {e}")
    return None


# ---------------------------------------------------------------------------
# 10.6 virus_scan — Media safety
# ---------------------------------------------------------------------------
async def virus_scan(
    file_bytes: bytes,
    filename: str = "upload.bin",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Scan a file for malware using VirusTotal API.

    Args:
        file_bytes: File content bytes
        filename: Filename
        api_key: VirusTotal API key

    Returns:
        Dict with safe (bool), scan_id, and report
    """
    api_key = api_key or os.getenv("VIRUSTOTAL_API_KEY", "")
    if not api_key:
        return {"safe": True, "skipped": True, "reason": "No API key configured"}

    try:
        import hashlib
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        async with httpx.AsyncClient(timeout=30) as client:
            headers = {"x-apikey": api_key}
            resp = await client.get(
                f"https://www.virustotal.com/api/v3/files/{file_hash}",
                headers=headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            stats = data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
            malicious = stats.get("malicious", 0)
            return {
                "safe": malicious == 0,
                "malicious_count": malicious,
                "scan_id": data.get("data", {}).get("id"),
                "report": stats,
            }
        elif resp.status_code == 404:
            # Upload file for scanning
            async with httpx.AsyncClient(timeout=60) as client:
                headers = {"x-apikey": api_key}
                files = {"file": (filename, file_bytes)}
                resp = await client.post(
                    "https://www.virustotal.com/api/v3/files",
                    files=files,
                    headers=headers,
                )
            if resp.status_code in (200, 201):
                return {"safe": True, "pending": True, "scan_id": resp.json().get("data", {}).get("id")}
        logger.error(f"Virus scan failed: {resp.text}")
    except Exception as scan_error:
        logger.error(f"Virus scan error: {scan_error}")
        return {"safe": True, "error": str(scan_error)}
    return {"safe": True, "error": "Unknown error"}


# ---------------------------------------------------------------------------
# 10.7 spellcheck_business_reply — Polishes outgoing messages
# ---------------------------------------------------------------------------
async def spellcheck_business_reply(
    text: str,
    language: str = "en",
    api_key: Optional[str] = None,
) -> str:
    """
    Check and correct spelling/grammar in business replies.
    Polishes outgoing messages without changing tone.

    Args:
        text: Text to check
        language: Language code
        api_key: OpenAI API key

    Returns:
        Corrected text (or original if no corrections)
    """
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return text

    prompt = (
        f"Check the following business reply for spelling and grammar errors. "
        f"Fix only errors, keep the same tone and meaning. "
        f"Return ONLY the corrected text:\n\n{text}"
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        if resp.status_code == 200:
            result = resp.json()
            corrected = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return corrected or text
    except Exception as e:
        logger.error(f"Spellcheck error: {e}")
    return text
