"""Range, type and cross-field validation for canonical parameters (E-PARAM-1).

Validation is pure and deterministic.  It distinguishes hard ERRORS from
WARNINGS.  An invalid configuration can never be accepted as effective because
:class:`~backend.strategy.parameters.model.StrategyParameterSet` refuses to be
constructed when errors are present.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from .registry import StrategyParameterRegistry, ValueType


class ValidationCode(str, Enum):
    """Stable validation issue codes."""

    INVALID_CONTAINER = "INVALID_CONTAINER"
    UNKNOWN_PARAMETER = "UNKNOWN_PARAMETER"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_TYPE = "INVALID_TYPE"
    NON_FINITE = "NON_FINITE"
    NOT_INTEGRAL = "NOT_INTEGRAL"
    BELOW_MINIMUM = "BELOW_MINIMUM"
    ABOVE_MAXIMUM = "ABOVE_MAXIMUM"
    HOLD_TIME_ORDER = "HOLD_TIME_ORDER"
    MOMENTUM_WARMUP_ORDER = "MOMENTUM_WARMUP_ORDER"
    CONFIDENCE_EXCEEDS_COMPOSITE = "CONFIDENCE_EXCEEDS_COMPOSITE"
    EXIT_MOMENTUM_HIGH = "EXIT_MOMENTUM_HIGH"


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding."""

    code: ValidationCode
    message: str
    parameter: Optional[str] = None


@dataclass(frozen=True)
class ValidationResult:
    """Distinct hard errors and soft warnings."""

    errors: Tuple[ValidationIssue, ...] = ()
    warnings: Tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "isValid": self.is_valid,
            "errors": [
                {
                    "code": issue.code.value,
                    "parameter": issue.parameter,
                    "message": issue.message,
                }
                for issue in self.errors
            ],
            "warnings": [
                {
                    "code": issue.code.value,
                    "parameter": issue.parameter,
                    "message": issue.message,
                }
                for issue in self.warnings
            ],
        }


def _coerce_number(
    name: str,
    value: Any,
    value_type: ValueType,
    errors: list,
) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(
            ValidationIssue(
                ValidationCode.INVALID_TYPE,
                f"{name} must be a finite numeric value, got "
                f"{type(value).__name__}",
                name,
            )
        )
        return None
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(
            ValidationIssue(
                ValidationCode.NON_FINITE,
                f"{name} must be finite (NaN/Infinity rejected)",
                name,
            )
        )
        return None
    if value_type is ValueType.INTEGER:
        if isinstance(value, float) and not value.is_integer():
            errors.append(
                ValidationIssue(
                    ValidationCode.NOT_INTEGRAL,
                    f"{name} must be an integer number of "
                    "milliseconds",
                    name,
                )
            )
            return None
        return int(value)
    return float(value)


def _validate_range(name: str, value: float, metadata, errors: list) -> None:
    if metadata.minimum_inclusive:
        if value < metadata.minimum:
            errors.append(
                ValidationIssue(
                    ValidationCode.BELOW_MINIMUM,
                    f"{name} must be >= {metadata.minimum}",
                    name,
                )
            )
            return
    elif value <= metadata.minimum:
        errors.append(
            ValidationIssue(
                ValidationCode.BELOW_MINIMUM,
                f"{name} must be > {metadata.minimum}",
                name,
            )
        )
        return
    if metadata.maximum is None:
        return
    if metadata.maximum_inclusive:
        if value > metadata.maximum:
            errors.append(
                ValidationIssue(
                    ValidationCode.ABOVE_MAXIMUM,
                    f"{name} must be <= {metadata.maximum}",
                    name,
                )
            )
    elif value >= metadata.maximum:
        errors.append(
            ValidationIssue(
                ValidationCode.ABOVE_MAXIMUM,
                f"{name} must be < {metadata.maximum}",
                name,
            )
        )


def validate_parameters(
    parameters: Any,
    *,
    require_complete: bool = False,
) -> ValidationResult:
    """Validate a mapping of canonical parameter values.

    ``require_complete`` additionally requires every registered canonical
    parameter to be present.
    """

    errors: list = []
    warnings: list = []

    if not isinstance(parameters, Mapping):
        return ValidationResult(
            errors=(
                ValidationIssue(
                    ValidationCode.INVALID_CONTAINER,
                    "parameters must be a mapping",
                    None,
                ),
            )
        )

    registry = StrategyParameterRegistry

    for name in parameters:
        if registry.get(name) is None:
            errors.append(
                ValidationIssue(
                    ValidationCode.UNKNOWN_PARAMETER,
                    f"unknown parameter '{name}'",
                    name,
                )
            )

    checked: dict = {}
    for metadata in registry.PARAMETERS:
        name = metadata.name
        if name not in parameters:
            if require_complete:
                errors.append(
                    ValidationIssue(
                        ValidationCode.MISSING_PARAMETER,
                        f"missing required parameter '{name}'",
                        name,
                    )
                )
            continue
        value = _coerce_number(
            name, parameters[name], metadata.value_type, errors
        )
        if value is None:
            continue
        checked[name] = value
        _validate_range(name, value, metadata, errors)

    _cross_field(checked, errors, warnings)

    return ValidationResult(
        errors=tuple(errors), warnings=tuple(warnings)
    )


def _cross_field(checked: Mapping[str, float], errors: list, warnings: list) -> None:
    minimum_hold = checked.get("minimumHoldMs")
    maximum_hold = checked.get("maximumHoldMs")
    if minimum_hold is not None and maximum_hold is not None:
        if minimum_hold >= maximum_hold:
            errors.append(
                ValidationIssue(
                    ValidationCode.HOLD_TIME_ORDER,
                    "minimumHoldMs must be strictly less than maximumHoldMs",
                    "minimumHoldMs",
                )
            )

    warmup = checked.get("momentumMinimumWarmupSeconds")
    window = checked.get("momentumWindowSeconds")
    if warmup is not None and window is not None:
        if warmup > window:
            errors.append(
                ValidationIssue(
                    ValidationCode.MOMENTUM_WARMUP_ORDER,
                    "momentumMinimumWarmupSeconds must be <= "
                    "momentumWindowSeconds",
                    "momentumMinimumWarmupSeconds",
                )
            )

    confidence = checked.get("minimumStrategyConfidence")
    composite = checked.get("minimumCompositeScore")
    if confidence is not None and composite is not None:
        if confidence > composite:
            warnings.append(
                ValidationIssue(
                    ValidationCode.CONFIDENCE_EXCEEDS_COMPOSITE,
                    "minimumStrategyConfidence is greater than "
                    "minimumCompositeScore; the confidence floor may never bind",
                    "minimumStrategyConfidence",
                )
            )

    exit_momentum = checked.get("exitMomentumMinimum")
    if exit_momentum is not None and exit_momentum > 0.5:
        warnings.append(
            ValidationIssue(
                ValidationCode.EXIT_MOMENTUM_HIGH,
                "exitMomentumMinimum is greater than 0.5 and may cause "
                "unusually early momentum-decay exits",
                "exitMomentumMinimum",
            )
        )
