"""
Granular Utility Functions — Small Functions, Big Impact
Organized by category for the WhatsApp Agent Platform.
"""

from .messaging import (
    is_duplicate_message,
    typing_indicator,
    split_long_message,
    randomized_delay,
    is_opted_out,
    detect_stop_keyword,
    normalize_phone_number,
    dedupe_incoming_media,
)

from .reliability import (
    retry_with_backoff,
    safe_tool_call,
    circuit_breaker,
    idempotency_key,
    heartbeat_ping,
    graceful_shutdown_handler,
)

from .memory import (
    extract_entities,
    merge_entity_update,
    summarize_conversation,
    is_pii,
    ttl_for_memory_type,
)

from .rag import (
    hash_document,
    chunk_with_overlap,
    confidence_threshold_check,
    cite_source,
    rerank_top_k,
)

from .leads import (
    classify_urgency,
    classify_sentiment,
    score_decay,
    notify_owner,
    next_best_action,
)

from .scheduling import (
    to_business_timezone,
    to_user_timezone,
    check_double_booking,
    generate_ics_invite,
    detect_reschedule_intent,
    mark_no_show,
)

from .payments import (
    generate_payment_link,
    verify_payment_webhook,
    on_payment_success,
    retry_failed_payment_reminder,
)

from .security import (
    verify_hmac_signature,
    is_request_stale,
    encrypt_field,
    decrypt_field,
    rate_limit,
    scrub_pii_from_logs,
)

from .analytics import (
    track_event,
    funnel_dropoff_report,
    average_response_time,
    most_asked_questions,
)

from .integrations import (
    whisper_transcribe,
    vision_describe,
    translate_text,
    geocode_address,
    short_url,
    virus_scan,
    spellcheck_business_reply,
)

__all__ = [
    # Messaging
    "is_duplicate_message", "typing_indicator", "split_long_message",
    "randomized_delay", "is_opted_out", "detect_stop_keyword",
    "normalize_phone_number", "dedupe_incoming_media",
    # Reliability
    "retry_with_backoff", "safe_tool_call", "circuit_breaker",
    "idempotency_key", "heartbeat_ping", "graceful_shutdown_handler",
    # Memory
    "extract_entities", "merge_entity_update", "summarize_conversation",
    "is_pii", "ttl_for_memory_type",
    # RAG
    "hash_document", "chunk_with_overlap", "confidence_threshold_check",
    "cite_source", "rerank_top_k",
    # Leads
    "classify_urgency", "classify_sentiment", "score_decay",
    "notify_owner", "next_best_action",
    # Scheduling
    "to_business_timezone", "to_user_timezone", "check_double_booking",
    "generate_ics_invite", "detect_reschedule_intent", "mark_no_show",
    # Payments
    "generate_payment_link", "verify_payment_webhook",
    "on_payment_success", "retry_failed_payment_reminder",
    # Security
    "verify_hmac_signature", "is_request_stale", "encrypt_field",
    "decrypt_field", "rate_limit", "scrub_pii_from_logs",
    # Analytics
    "track_event", "funnel_dropoff_report", "average_response_time",
    "most_asked_questions",
    # Integrations
    "whisper_transcribe", "vision_describe", "translate_text",
    "geocode_address", "short_url", "virus_scan", "spellcheck_business_reply",
]