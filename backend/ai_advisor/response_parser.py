"""Strict JSON parsing for future AI Advisor provider responses."""

import json

from pydantic import ValidationError

from backend.ai_advisor.response_models import (
    AdvisorRawResponse,
    AdvisorResponseCandidate,
)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_advisor_response(
    raw_response: AdvisorRawResponse,
) -> AdvisorResponseCandidate:
    """Decode one complete JSON object without repair or inference."""

    if not isinstance(raw_response, AdvisorRawResponse):
        raise TypeError("typed AdvisorRawResponse required")
    try:
        raw_response = AdvisorRawResponse.model_validate(raw_response.model_dump())
        decoded = json.loads(
            raw_response.responseText,
            object_pairs_hook=_reject_duplicate_keys,
        )
        if not isinstance(decoded, dict):
            raise ValueError
        return AdvisorResponseCandidate.model_validate_json(raw_response.responseText)
    except (
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        TypeError,
        RecursionError,
        OverflowError,
    ):
        raise ValueError("advisor response parsing failed") from None
