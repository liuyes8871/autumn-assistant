from __future__ import annotations

from dataclasses import dataclass


# 405 is commonly returned by a public career page when the endpoint only
# accepts browser navigation or a different method.  Treat it like the other
# access-control responses: never retry it and never mistake it for an empty
# feed.
NON_RETRYABLE_STATUS = {401, 403, 405, 429}


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    reason: str
    delay_seconds: float = 0.0


def retry_decision(status_code: int | None, attempt: int, max_attempts: int = 3) -> RetryDecision:
    """Low-frequency retry policy: timeout/5xx only; never bypass controls."""

    if status_code in NON_RETRYABLE_STATUS:
        return RetryDecision(False, f"access_control_or_rate_limit:{status_code}")
    if status_code is None:
        return RetryDecision(attempt < max_attempts, "network_timeout", min(30.0, 2**attempt))
    if 500 <= status_code <= 599:
        return RetryDecision(attempt < max_attempts, f"server_error:{status_code}", min(30.0, 2**attempt))
    return RetryDecision(False, f"non_retryable_status:{status_code}")
