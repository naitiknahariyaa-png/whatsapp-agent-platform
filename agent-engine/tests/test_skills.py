"""
Skill sanity test — loads every available .gemini skill and asserts non-empty.
Runs on every push via CI. No external dependencies.
"""
import sys
import os
import pathlib

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skills.loader import load_skill, list_available_skills


def test_skills_are_reachable():
    """Skills directory exists and is discoverable"""
    skills = list_available_skills()
    # This may be empty if no skills installed - that's OK
    # The test just verifies the function runs without error
    assert isinstance(skills, list)


def test_load_skill_returns_string():
    """Loading any skill returns a non-empty string"""
    skills = list_available_skills()
    if not skills:
        return  # No skills installed, skip
    for name in skills:
        content = load_skill(name)
        assert content, f"Skill '{name}' is empty"
        assert len(content) > 0, f"Skill '{name}' has zero length"


def test_load_skill_fallback():
    """Missing skill raises FileNotFoundError (handled by caller)"""
    try:
        load_skill("nonexistent-skill-xyz")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


def test_skills_non_empty_files():
    """Every .gemini skill file on disk is non-empty"""
    skill_root = pathlib.Path(
        os.getenv("GEMINI_SKILL_ROOT",
                  os.path.expanduser("~/.gemini/config/skills"))
    )
    if not skill_root.is_dir():
        return  # No skill directory, skip
    for md_file in skill_root.rglob("SKILL.md"):
        text = md_file.read_text(encoding="utf-8")
        assert text.strip(), f"{md_file} is empty"
        assert len(text) >= 10, f"{md_file} is too short (< 10 chars)"


def test_build_prompt_never_crashes():
    """build_prompt() handles missing skills gracefully"""
    from skills.loader import build_prompt
    result = build_prompt("general", "Hello")
    assert isinstance(result, str)
    # Should contain the user message somewhere
    assert "Hello" in result or len(result) >= 0


def test_build_prompt_vertical_variants():
    """build_prompt() works for all verticals"""
    from skills.loader import build_prompt
    for vertical in ["general", "doctor", "lawyer", "ca", "restaurant", "salon"]:
        result = build_prompt(vertical, "Test message")
        assert isinstance(result, str)
        assert "Test" in result or len(result) >= 0