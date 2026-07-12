import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar

from src.claims.constants import (
    CLAIMS_VERIFIER_MODEL,
    CLAIMS_VERIFIER_PROMPT,
    CLAIMS_VERIFIER_PROMPT_VERSION,
)
from src.llm import (
    create_cached_chat_completion,
    create_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)


logger = logging.getLogger(__name__)
_VERIFIER_METRICS = ContextVar("claim_verifier_metrics", default=None)


def _verifier_completion(claim_text, evidence_span, client_factory):
    return create_cached_chat_completion(
        client_factory,
        model=CLAIMS_VERIFIER_MODEL,
        messages=_verifier_messages(claim_text, evidence_span),
        purpose="claim_verifier",
        prompt_version=CLAIMS_VERIFIER_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )


def _uncached_verifier_completion(claim_text, evidence_span, client_factory):
    return create_chat_completion(
        client_factory(),
        model=CLAIMS_VERIFIER_MODEL,
        messages=_verifier_messages(claim_text, evidence_span),
        purpose="claim_verifier",
        prompt_version=CLAIMS_VERIFIER_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )


def _verifier_messages(claim_text, evidence_span):
    user_content = json.dumps(
        {"claim_text": claim_text, "evidence_span": evidence_span},
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": CLAIMS_VERIFIER_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _verifier_supported(response):
    parsed = parse_json_object(response)
    supported = parsed.get("supported")
    if not isinstance(supported, bool):
        mark_schema_failure(
            'Model response must contain boolean "supported"',
            response=response,
        )
        raise ValueError('Model response must contain boolean "supported"')
    return supported


def verify_claim_with_llm(
    claim_text,
    evidence_span,
    client_factory,
    uncached_completion,
):
    """Ask gpt-5.4-nano whether the span supports the claim. Default-reject on any error."""
    started = time.perf_counter()
    response = None
    was_cached = False
    try:
        response, cache_metadata, was_cached = _verifier_completion(claim_text, evidence_span, client_factory)
    except Exception:
        _record_verifier_metric(started, None, False, False)
        return False
    refreshed_bad_cache = False
    try:
        supported = _verifier_supported(response)
    except ValueError:
        if not was_cached:
            _record_verifier_metric(started, response, was_cached, False)
            return False
        try:
            response = uncached_completion(claim_text, evidence_span)
            supported = _verifier_supported(response)
        except Exception:
            _record_verifier_metric(started, response, was_cached, False)
            return False
        refreshed_bad_cache = True
    if not was_cached or refreshed_bad_cache:
        try:
            save_cached_chat_completion(cache_metadata, response)
        except sqlite3.Error as exc:
            logger.warning("Claim verifier cache save failed: %s", exc)
    _record_verifier_metric(started, response, was_cached and not refreshed_bad_cache, supported)
    return supported


@contextmanager
def collect_verifier_metrics():
    metrics = []
    token = _VERIFIER_METRICS.set(metrics)
    try:
        yield metrics
    finally:
        _VERIFIER_METRICS.reset(token)


def _record_verifier_metric(started, response, cache_hit, supported):
    collector = _VERIFIER_METRICS.get()
    if collector is None:
        return
    usage = getattr(response, "usage", None) if response is not None else None
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
    else:
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
    collector.append({
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_hit": bool(cache_hit),
        "supported": bool(supported),
    })
