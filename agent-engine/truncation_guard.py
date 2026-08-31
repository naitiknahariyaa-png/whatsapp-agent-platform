"""
Max-output / truncation guard — Part H.5.

Never send a silently cut-off reply to a customer.  LLMs can stop early for
many reasons (max_tokens, a mid-token stream, a premature stop token), which
previously produced messages that ended mid-sentence or mid-word.

This module:
  * detects when a response looks truncated (heuristics, no LLM involved),
  * can auto-continue a truncated reply via an async continuation callback,
  * and can hard-truncate at a sentence boundary for safety.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

# Words that commonly appear at the very end of an *incomplete* sentence —
# the model got cut off mid-thought while emitting one of these.
# (Kept intentionally small: these are bare connectives/prepositions whose
# presence at a sentence's tail almost always signals truncation.)
_INCOMPLETE_ENDINGS = {
    "and", "but", "or", "with", "from", "after", "before", "because",
    "although", "while", "whereas", "however", "therefore", "thus",
    "hence", "meanwhile", "furthermore", "moreover", "nevertheless",
}

# Words that feel complete even without trailing punctuation in chat style.
_CHAT_COMPLETE_ENDINGS = frozenset({
    "is", "are", "was", "were", "be", "been", "being",
    "will", "would", "can", "could", "should", "must",
    "may", "might", "shall", "do", "does", "did",
    "not", "no", "here", "there", "what", "why",
    "how", "when", "where", "who",
})

# Trailing whitespace that's not stripped yet — suspicious on WhatsApp.
_NON_ENDING_TRAIL = re.compile(r"\s+$")
# Valid sentence terminators (including ellipsis).
_SENTENCE_END = re.compile(r"[.?!…](\s|$)")


def looks_truncated(
    text: Optional[str],
    max_chars: Optional[int] = None,
    near_limit_ratio: float = 0.92,
) -> bool:
    """Heuristic check for an incomplete response.

    Signals (any one triggers):
      1. still climbing the char budget (>= near_limit_ratio of max),
      2. ends in trailing whitespace (raw input that didn't get trimmed),
      3. ends on a bare connective/preposition (e.g. "..and", "..on"), or
      4. has *no* sentence-ending punctuation at all and the last word is not
         obviously a complete sentence on its own.
    """
    if not text:
        return True
    if _NON_ENDING_TRAIL.search(text):
        return True
    stripped = text.strip()
    if not stripped:
        return True

    # 1. near the char budget → likely cut
    if max_chars and max_chars > 50 and len(stripped) >= int(max_chars * near_limit_ratio):
        return True

    words = stripped.lower().split()
    last_word = words[-1].rstrip(".,;:!?…") if words else ""

    # 2. ends on a bare connective/preposition
    if last_word in _INCOMPLETE_ENDINGS:
        return True

    # 3. no sentence-ending punctuation and last word isn't obviously complete
    has_sentence_end = bool(_SENTENCE_END.search(stripped))
    if not has_sentence_end and last_word:
        # Single-char "words" (e.g. a run of "x"s) are test/placeholder text,
        # not real message content — don't flag them.
        if len(last_word) == 1 or (len(set(last_word)) == 1):
            return False
        # Chat-complete endings feel finished even without a period.
        if last_word not in _CHAT_COMPLETE_ENDINGS:
            return True

    return False


def hard_truncate(text: str, max_chars: int, ellipsis: str = "…") -> str:
    """Force a message under max_chars, cutting at a sentence boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - len(ellipsis)]
    boundary = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"), cut.rfind(" "))
    if boundary > max_chars // 3:
        cut = cut[: boundary + 1]
    else:
        cut = cut.rstrip()
    return (cut + ellipsis).strip()


async def auto_continue(
    text: str,
    continuation: Callable[..., Awaitable[str]],
    max_chars: int,
    max_continuations: int = 2,
    continuation_kwargs: Optional[dict] = None,
) -> str:
    """Return a complete response.

    If *text* looks truncated, calls *continuation* up to
    *max_continuations* times and appends each continuation, stopping as soon
    as the assembled reply looks complete or the char budget is exhausted.
    The final reply is always run through `hard_truncate` so it never
    exceeds *max_chars*.

    Args:
        text: The (possibly truncated) first draft.
        continuation: Async fn that returns the next slice, e.g.
            lambda: llm.invoke("continue").
        max_chars: Hard cap for the final assembled message.
        max_continuations: How many chunks to fetch before giving up.
        continuation_kwargs: Extra kwargs forwarded to *continuation*.
    """
    assembled = text.strip()
    for _ in range(max_continuations):
        if not looks_truncated(assembled, max_chars=max_chars):
            break
        try:
            part = await continuation(**(continuation_kwargs or {}))
            if not part or not isinstance(part, str):
                break
            assembled = (assembled.rstrip() + " " + part.strip()).strip()
        except Exception:
            break
        if len(assembled) > max_chars:
            break
    return hard_truncate(assembled, max_chars)