"""Immutable provider resolution without import-time construction."""

from types import MappingProxyType
from typing import Callable, Mapping

from backend.ai_advisor.provider_adapter import AdvisorProvider
from backend.ai_advisor.provider_config import ProviderConnectionConfig, ProviderName

ProviderFactory = Callable[[ProviderConnectionConfig], AdvisorProvider]


class ProviderRegistry:
    def __init__(self, factories: Mapping[ProviderName, ProviderFactory]):
        copied = dict(factories)
        if ProviderName.DISABLED in copied:
            raise ValueError("disabled provider cannot be registered")
        if any(not isinstance(name, ProviderName) for name in copied):
            raise ValueError("unknown provider")
        self._factories = MappingProxyType(copied)

    def resolve(self, config: ProviderConnectionConfig) -> AdvisorProvider:
        try:
            trusted = ProviderConnectionConfig.model_validate(
                config.model_dump(warnings=False)
            )
        except Exception:
            raise ValueError("advisor provider configuration invalid") from None
        if trusted.provider is ProviderName.DISABLED or trusted.enabled is not True:
            raise ValueError("advisor provider disabled")
        factory = self._factories.get(trusted.provider)
        if factory is None:
            raise ValueError("advisor provider unsupported")
        try:
            return factory(trusted)
        except Exception:
            raise ValueError("advisor provider unavailable") from None
