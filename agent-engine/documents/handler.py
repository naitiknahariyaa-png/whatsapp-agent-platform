"""
Document handler - WhatsApp media download and PDF parsing
"""
import fitz  # PyMuPDF
import base64
import os
from pathlib import Path
from typing import Optional, Dict, Any

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def save_base64_file(base64_data: str, filename: str, phone_number: str) -> str:
    """Save base64 encoded file to disk"""
    file_path = UPLOAD_DIR / f"{phone_number}_{filename}"
    with open(file_path, "wb") as f:
        f.write(base64.b64decode(base64_data))
    return str(file_path)


def extract_pdf_text(pdf_path: str) -> str:
    """Extract text from PDF using PyMuPDF"""
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()
    except Exception as e:
        return f"Error parsing PDF: {str(e)}"


def process_whatsapp_media(media_data: Dict[str, Any], phone_number: str) -> Optional[str]:
    """
    Process WhatsApp media message
    Returns extracted text if PDF, otherwise file path
    """
    mimetype = media_data.get("mimetype", "")
    base64_data = media_data.get("data", "")
    filename = media_data.get("filename", f"file_{phone_number}")
    
    if not base64_data:
        return None
    
    file_path = save_base64_file(base64_data, filename, phone_number)
    
    # If PDF, extract text
    if mimetype == "application/pdf" or filename.endswith(".pdf"):
        return extract_pdf_text(file_path)
    
    return file_path