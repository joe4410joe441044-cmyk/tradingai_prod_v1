from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.supervisor.operator_constitution import (
    OperatorConstitution,
    TRADINGAI_OPERATOR_CONSTITUTION,
    constitution_identity,
)


def test_operator_constitution_is_fixed_versioned_immutable_and_deterministic():
    constitution = TRADINGAI_OPERATOR_CONSTITUTION
    identity = constitution_identity(constitution)

    assert constitution.constitutionId == "TRADINGAI_OPERATOR_CONSTITUTION"
    assert constitution.constitutionVersion == "1.0"
    assert constitution.longTermSurvivalRequired is True
    assert constitution.capitalProtectionRequired is True
    assert constitution.profitPursuitAllowed is True
    assert constitution.compoundingAllowedWithinPolicy is True
    assert constitution.riskContractionOnDegradation is True
    assert constitution.hardSafetyAlwaysOverrides is True
    assert constitution.governanceAlwaysOverrides is True
    assert constitution.agentMayRewriteConstitution is False
    assert identity.constitutionDigest == constitution.digest()
    assert len(identity.constitutionDigest) == 64
    assert constitution.stable_json() == TRADINGAI_OPERATOR_CONSTITUTION.stable_json()
    with pytest.raises(ValidationError):
        constitution.profitPursuitAllowed = False


def test_constitution_has_no_implicit_policy_defaults_and_rejects_rewrite_flags():
    assert all(field.is_required() for field in OperatorConstitution.model_fields.values())
    data = TRADINGAI_OPERATOR_CONSTITUTION.model_dump(mode="python")
    data["agentMayRewriteConstitution"] = True
    with pytest.raises(ValidationError):
        OperatorConstitution.model_validate(data)
    data = TRADINGAI_OPERATOR_CONSTITUTION.model_dump(mode="python")
    data["hardSafetyAlwaysOverrides"] = False
    with pytest.raises(ValidationError):
        OperatorConstitution.model_validate(data)
    data = TRADINGAI_OPERATOR_CONSTITUTION.model_dump(mode="python")
    data["effectiveAt"] = datetime(2026, 8, 12)
    with pytest.raises(ValidationError):
        OperatorConstitution.model_validate(data)
