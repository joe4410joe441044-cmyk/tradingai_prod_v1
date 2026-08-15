"""Bounded normalization for source-less provider responses."""

import json

from backend.ai_advisor.response_models import AdvisorRawResponse


_TOP_LEVEL_FIELDS = {
    "responseVersion",
    "requestId",
    "promptVersion",
    "summary",
    "facts",
    "inferences",
    "unknowns",
    "warnings",
    "sourceReferences",
    "freshnessDisclosures",
    "safetyDisclosures",
}
_FACT_FIELDS = {"factId", "statement", "sourceIds", "freshness"}
_INFERENCE_FIELDS = {
    "inferenceId",
    "statement",
    "basedOnSourceIds",
    "uncertainty",
}


def _strict_object(text: str):
    def reject_constant(_value):
        raise ValueError

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    return json.loads(
        text,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def normalize_no_source_response(
    raw_response: AdvisorRawResponse,
) -> AdvisorRawResponse:
    """Discard only explicitly ungrounded claim collections in no-source mode.

    The normalizer deliberately does not repair JSON, remove unknown fields, or
    accept a claimed source. Any such response remains unchanged and is rejected
    by the ordinary strict parser/validator.
    """

    try:
        decoded = _strict_object(raw_response.responseText)
        if not isinstance(decoded, dict) or set(decoded) != _TOP_LEVEL_FIELDS:
            return raw_response
        if decoded["sourceReferences"] != [] or decoded["freshnessDisclosures"] != []:
            return raw_response
        facts = decoded["facts"]
        inferences = decoded["inferences"]
        if not isinstance(facts, list) or not isinstance(inferences, list):
            return raw_response
        if any(
            not isinstance(item, dict)
            or set(item) != _FACT_FIELDS
            or item.get("sourceIds") != []
            for item in facts
        ):
            return raw_response
        if any(
            not isinstance(item, dict)
            or set(item) != _INFERENCE_FIELDS
            or item.get("basedOnSourceIds") != []
            for item in inferences
        ):
            return raw_response
    except (TypeError, ValueError, json.JSONDecodeError):
        return raw_response

    if not facts and not inferences:
        return raw_response
    decoded["facts"] = []
    decoded["inferences"] = []
    return raw_response.model_copy(
        update={
            "responseText": json.dumps(
                decoded,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        }
    )
