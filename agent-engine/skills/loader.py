"""
Skill loader - reads .gemini skill markdown files and injects them into LLM prompts.
Runtime isolation: heavy native dependencies are wrapped in try/except ImportError.
If a dependency is missing, the loader falls back to a stub gracefully.
"""
import pathlib
import os

# Default skill root (Antigravity environment)
DEFAULT_SKILL_ROOT = pathlib.Path(r"C:\Users\PC\.gemini\config\skills")

# ---------------------------------------------------------------------------
# External dependency stubs (isolated imports)
# ---------------------------------------------------------------------------

# ChromaDB — optional vector memory. Falls back to dict-based stub if missing.
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _has_chroma = True
except ImportError:
    _has_chroma = False

# Sentence Transformers — optional embeddings. Falls back to identity if missing.
try:
    from sentence_transformers import SentenceTransformer
    _has_sentence_tf = True
except ImportError:
    _has_sentence_tf = False

# PyMuPDF — optional PDF parsing. Falls back to text-only stub if missing.
try:
    import fitz
    _has_fitz = True
except ImportError:
    _has_fitz = False


def _stub_embed(text: str) -> list:
    """Fallback embedding when sentence-transformers is not installed."""
    return [0.0] * 384  # Return zero vector of standard size


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_skill_root() -> pathlib.Path:
    """Get the skill root directory from env or default"""
    env_path = os.getenv("GEMINI_SKILL_ROOT")
    if env_path:
        return pathlib.Path(env_path)
    return DEFAULT_SKILL_ROOT


def load_skill(name: str) -> str:
    """
    Load a skill Markdown file and return its body as a string.
    Looks for: <skill_root>/<name>/SKILL.md
    """
    skill_root = get_skill_root()
    md_path = skill_root / name / "SKILL.md"
    if not md_path.is_file():
        raise FileNotFoundError(f"Skill '{name}' not found at {md_path}")
    return md_path.read_text(encoding="utf-8")


def list_available_skills() -> list:
    """List all available skill names"""
    skill_root = get_skill_root()
    if not skill_root.is_dir():
        return []
    return [d.name for d in skill_root.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()]


def build_prompt(vertical: str, user_msg: str) -> str:
    """
    Build a combined LLM prompt using core skill + vertical-specific skill.
    Falls back gracefully if skills are not available.
    """
    # Core skill (generic LLM best practices)
    core_prompt = ""
    try:
        core_prompt = load_skill("anthropic-cookbook")
    except FileNotFoundError:
        pass

    # Vertical-specific skill
    vertical_skills = {
        "doctor": "doctor-skill",
        "lawyer": "lawyer-skill",
        "ca": "ca-skill",
        "restaurant": "restaurant-skill",
        "salon": "salon-skill",
        "general": "general-assistant",
    }

    vert_skill_name = vertical_skills.get(vertical, "")
    vert_prompt = ""
    if vert_skill_name:
        try:
            vert_prompt = load_skill(vert_skill_name)
        except FileNotFoundError:
            pass

    # Optional tutoring flavour for complex questions
    tutor_prompt = ""
    if "explain" in user_msg.lower() or "kya" in user_msg.lower():
        try:
            tutor_prompt = load_skill("iit-tutor")
        except FileNotFoundError:
            pass

    # Combine all prompts
    parts = [p for p in [core_prompt, vert_prompt, tutor_prompt] if p]
    combined = "\n\n".join(parts)
    if combined:
        combined += f"\n\nUser: {user_msg}"
    else:
        combined = user_msg

    return combined


def has_chroma() -> bool:
    """Check if ChromaDB is available at runtime"""
    return _has_chroma


def has_embeddings() -> bool:
    """Check if sentence-transformers is available at runtime"""
    return _has_sentence_tf


def has_pdf_support() -> bool:
    """Check if PyMuPDF is available at runtime"""
    return _has_fitz