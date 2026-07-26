"""Secret-safe HTTP authentication and authorization boundary."""

import hmac
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from backend.ai_advisor.api_models import AdvisorAPIPrincipal
from backend.ai_advisor.credential_loader import (
    CredentialLoader,
    CredentialResolutionInput,
    CredentialResolutionStatus,
)
from backend.ai_advisor.provider_config import CredentialReference, ProviderName


class AdvisorAPIAuthenticator(Protocol):
    def authenticate(self, authorization_headers: Sequence[str]) -> AdvisorAPIPrincipal:
        """Return an authorized server-side principal or raise a safe error."""


class AdvisorAuthenticationError(ValueError):
    def __init__(self):
        super().__init__("Authentication required.")


class AdvisorAuthorizationError(ValueError):
    def __init__(self):
        super().__init__("Advisor access is not allowed.")


@dataclass(frozen=True)
class RejectingAdvisorAuthenticator:
    def authenticate(self, authorization_headers: Sequence[str]) -> AdvisorAPIPrincipal:
        raise AdvisorAuthenticationError()


@dataclass(frozen=True)
class InjectedBearerAuthenticator:
    principalId: str
    advisorAccessAllowed: bool
    _token: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.principalId, str)
            or not self.principalId.strip()
            or not isinstance(self.advisorAccessAllowed, bool)
            or not isinstance(self._token, str)
            or not self._token
            or self._token != self._token.strip()
            or any(character.isspace() for character in self._token)
        ):
            raise ValueError("advisor authenticator configuration invalid")

    def authenticate(self, authorization_headers: Sequence[str]) -> AdvisorAPIPrincipal:
        if len(authorization_headers) != 1:
            raise AdvisorAuthenticationError()
        header = authorization_headers[0]
        if (
            not isinstance(header, str)
            or not header.startswith("Bearer ")
            or header.count(" ") != 1
        ):
            raise AdvisorAuthenticationError()
        token = header[7:]
        if not token or not hmac.compare_digest(token, self._token):
            raise AdvisorAuthenticationError()
        principal = AdvisorAPIPrincipal(
            principalId=self.principalId,
            authenticated=True,
            advisorAccessAllowed=self.advisorAccessAllowed,
        )
        if principal.advisorAccessAllowed is not True:
            raise AdvisorAuthorizationError()
        return principal


@dataclass(frozen=True)
class CredentialLoaderBearerAuthenticator:
    principalId: str
    advisorAccessAllowed: bool
    credentialReference: CredentialReference = field(repr=False)
    credentialLoader: CredentialLoader = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.principalId, str)
            or not self.principalId.strip()
            or not isinstance(self.advisorAccessAllowed, bool)
        ):
            raise ValueError("advisor authenticator configuration invalid")

    def authenticate(self, authorization_headers: Sequence[str]) -> AdvisorAPIPrincipal:
        if len(authorization_headers) != 1:
            raise AdvisorAuthenticationError()
        header = authorization_headers[0]
        if (
            not isinstance(header, str)
            or not header.startswith("Bearer ")
            or header.count(" ") != 1
        ):
            raise AdvisorAuthenticationError()
        supplied = header[7:]
        if not supplied:
            raise AdvisorAuthenticationError()
        try:
            result = self.credentialLoader.resolve(
                CredentialResolutionInput(
                    credentialReference=self.credentialReference,
                    provider=ProviderName.OPENAI,
                    allowEnvironmentRead=(
                        self.credentialReference.source.value == "ENVIRONMENT"
                    ),
                )
            )
            if (
                result.status is not CredentialResolutionStatus.SUCCEEDED
                or result.credential is None
                or not hmac.compare_digest(
                    supplied,
                    result.credential._consume(),
                )
            ):
                raise AdvisorAuthenticationError()
        except AdvisorAuthenticationError:
            raise
        except Exception:
            raise AdvisorAuthenticationError() from None
        principal = AdvisorAPIPrincipal(
            principalId=self.principalId,
            authenticated=True,
            advisorAccessAllowed=self.advisorAccessAllowed,
        )
        if principal.advisorAccessAllowed is not True:
            raise AdvisorAuthorizationError()
        return principal
