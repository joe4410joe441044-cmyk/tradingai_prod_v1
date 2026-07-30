"""Strict JSON parsing for future AI Advisor provider responses."""

import json

from pydantic import ValidationError

from backend.ai_advisor.provider_failure_observation import (
    ResponseContractDiagnostic,
    ResponseContractField,
    ResponseTopLevelType,
    ResponseValidationCode,
)
from backend.ai_advisor.response_models import (
    AdvisorRawResponse,
    AdvisorResponseCandidate,
)

_TOP_LEVEL_FIELDS = tuple(
    field
    for field in ResponseContractField
    if field is not ResponseContractField.UNKNOWN_OR_UNEXPECTED
)
_FIELD_BY_NAME = {field.value: field for field in _TOP_LEVEL_FIELDS}
_NULLABLE_NESTED_FIELDS = {"requiredSourceType", "message"}
_NESTED_COLLECTIONS = {
    "facts",
    "inferences",
    "unknowns",
    "warnings",
    "freshnessDisclosures",
}


class AdvisorResponseParsingError(ValueError):
    """Fixed, secret-free parser failure with allowlisted diagnostics only."""

    def __init__(self, diagnostic: ResponseContractDiagnostic):
        self.diagnostic = ResponseContractDiagnostic.model_validate(
            diagnostic.model_dump(warnings=False)
        )
        super().__init__("advisor response parsing failed")


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _top_level_type(value) -> ResponseTopLevelType:
    if value is None:
        return ResponseTopLevelType.NULL
    if isinstance(value, bool):
        return ResponseTopLevelType.BOOLEAN
    if isinstance(value, dict):
        return ResponseTopLevelType.OBJECT
    if isinstance(value, list):
        return ResponseTopLevelType.ARRAY
    if isinstance(value, str):
        return ResponseTopLevelType.STRING
    if isinstance(value, int):
        return ResponseTopLevelType.INTEGER
    if isinstance(value, float):
        return ResponseTopLevelType.NUMBER
    return ResponseTopLevelType.UNKNOWN


def _field_from_location(location) -> ResponseContractField | None:
    if not location or not isinstance(location[0], str):
        return None
    return _FIELD_BY_NAME.get(location[0])


def _first_disallowed_null(decoded: dict) -> ResponseContractField | None:
    for field in _TOP_LEVEL_FIELDS:
        if field.value in decoded and decoded[field.value] is None:
            return field
    for collection_name in _NESTED_COLLECTIONS:
        collection = decoded.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            for name, value in item.items():
                if value is None and name not in _NULLABLE_NESTED_FIELDS:
                    return _FIELD_BY_NAME[collection_name]
    return None


def _candidate_diagnostic(
    validation_error: ValidationError,
    decoded: dict,
) -> ResponseContractDiagnostic:
    errors = validation_error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    missing = {
        field
        for error in errors
        if error.get("type") == "missing"
        and len(error.get("loc", ())) == 1
        and (field := _field_from_location(error.get("loc", ()))) is not None
    }
    if missing:
        ordered = tuple(field for field in _TOP_LEVEL_FIELDS if field in missing)
        return ResponseContractDiagnostic(
            validationCode=ResponseValidationCode.REQUIRED_FIELD_MISSING,
            topLevelType=ResponseTopLevelType.OBJECT,
            invalidField=ordered[0],
            missingFields=ordered,
        )
    if any(error.get("type") == "extra_forbidden" for error in errors):
        return ResponseContractDiagnostic(
            validationCode=ResponseValidationCode.UNEXPECTED_FIELD,
            topLevelType=ResponseTopLevelType.OBJECT,
            invalidField=ResponseContractField.UNKNOWN_OR_UNEXPECTED,
        )
    null_field = _first_disallowed_null(decoded)
    if null_field is not None:
        return ResponseContractDiagnostic(
            validationCode=ResponseValidationCode.NULL_NOT_ALLOWED,
            topLevelType=ResponseTopLevelType.OBJECT,
            invalidField=null_field,
        )
    first = errors[0] if errors else {}
    location = first.get("loc", ())
    invalid_field = _field_from_location(location)
    error_type = first.get("type")
    if len(location) > 1 and error_type in {
        "missing",
        "model_type",
        "model_attributes_type",
    }:
        code = ResponseValidationCode.NESTED_SCHEMA_INVALID
    elif error_type in {"enum", "literal_error"}:
        code = ResponseValidationCode.ENUM_VALUE_INVALID
    elif error_type in {
        "string_type",
        "tuple_type",
        "list_type",
        "dict_type",
        "bool_type",
        "int_type",
        "float_type",
        "model_type",
        "model_attributes_type",
    }:
        code = ResponseValidationCode.FIELD_TYPE_INVALID
    elif error_type in {
        "string_too_short",
        "string_too_long",
        "too_short",
        "too_long",
    }:
        code = ResponseValidationCode.CONSTRAINT_VIOLATION
    elif len(location) > 1:
        code = ResponseValidationCode.NESTED_SCHEMA_INVALID
    elif errors:
        code = ResponseValidationCode.RESPONSE_CANDIDATE_INVALID
    else:
        code = ResponseValidationCode.UNKNOWN_RESPONSE_CONTRACT_FAILURE
    return ResponseContractDiagnostic(
        validationCode=code,
        topLevelType=ResponseTopLevelType.OBJECT,
        invalidField=invalid_field,
    )


def parse_advisor_response(
    raw_response: AdvisorRawResponse,
) -> AdvisorResponseCandidate:
    """Decode one complete JSON object without repair or inference."""

    if not isinstance(raw_response, AdvisorRawResponse):
        raise TypeError("typed AdvisorRawResponse required")
    try:
        raw_response = AdvisorRawResponse.model_validate(
            raw_response.model_dump(warnings=False)
        )
    except (ValidationError, ValueError, TypeError):
        raise AdvisorResponseParsingError(
            ResponseContractDiagnostic(
                validationCode=(
                    ResponseValidationCode.UNKNOWN_RESPONSE_CONTRACT_FAILURE
                ),
                topLevelType=ResponseTopLevelType.UNKNOWN,
            )
        ) from None
    try:
        decoded = json.loads(
            raw_response.responseText,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except _DuplicateKeyError:
        raise AdvisorResponseParsingError(
            ResponseContractDiagnostic(
                validationCode=ResponseValidationCode.DUPLICATE_KEY,
                topLevelType=ResponseTopLevelType.UNKNOWN,
            )
        ) from None
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
        OverflowError,
    ):
        raise AdvisorResponseParsingError(
            ResponseContractDiagnostic(
                validationCode=ResponseValidationCode.JSON_DECODE_FAILED,
                topLevelType=ResponseTopLevelType.UNKNOWN,
            )
        ) from None
    if not isinstance(decoded, dict):
        raise AdvisorResponseParsingError(
            ResponseContractDiagnostic(
                validationCode=ResponseValidationCode.TOP_LEVEL_NOT_OBJECT,
                topLevelType=_top_level_type(decoded),
            )
        )
    try:
        return AdvisorResponseCandidate.model_validate_json(raw_response.responseText)
    except ValidationError as exception:
        raise AdvisorResponseParsingError(
            _candidate_diagnostic(exception, decoded)
        ) from None
    except Exception:
        raise AdvisorResponseParsingError(
            ResponseContractDiagnostic(
                validationCode=(
                    ResponseValidationCode.UNKNOWN_RESPONSE_CONTRACT_FAILURE
                ),
                topLevelType=ResponseTopLevelType.OBJECT,
            )
        ) from None
