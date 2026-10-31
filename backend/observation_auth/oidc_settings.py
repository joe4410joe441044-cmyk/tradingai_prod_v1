"""Environment boundary for observation OIDC.

Credentials are read only when ``TRADINGAI_OBSERVATION_OIDC_ENABLED`` is the
exact string ``true``.  Any other value, including a missing variable, leaves
the feature off and does not retain secret values.  This module does not
write environment variables, files, or logs.
"""
import json
import os
from dataclasses import dataclass

from backend.observation_auth.oidc_config import (
    EXPECTED_ISSUER, GOOGLE_CLIENT_TYPE, TOKEN_ENDPOINT_AUTH_METHOD,
    ObservationOidcConfig)


ENV_ENABLED = 'TRADINGAI_OBSERVATION_OIDC_ENABLED'
ENV_CLIENT_ID = 'TRADINGAI_OBSERVATION_OIDC_CLIENT_ID'
ENV_CLIENT_SECRET = 'TRADINGAI_OBSERVATION_OIDC_CLIENT_SECRET'
ENV_SESSION_SECRET = 'TRADINGAI_OBSERVATION_OIDC_SESSION_SECRET'
ENV_REDIRECT_URI = 'TRADINGAI_OBSERVATION_OIDC_REDIRECT_URI'
ENV_ALLOWLIST = 'TRADINGAI_OBSERVATION_OIDC_ALLOWLIST_JSON'
ENV_SESSION_TTL = 'TRADINGAI_OBSERVATION_OIDC_SESSION_TTL_SECONDS'

_FIELD_ENV = (
    ('enabled', ENV_ENABLED),
    ('client_id', ENV_CLIENT_ID),
    ('client_secret', ENV_CLIENT_SECRET),
    ('session_secret', ENV_SESSION_SECRET),
    ('redirect_uri', ENV_REDIRECT_URI),
    ('allowlist', ENV_ALLOWLIST),
    ('session_ttl_seconds', ENV_SESSION_TTL),
)
_MAX_ALLOWLIST_BYTES = 8192


@dataclass(frozen=True)
class ObservationOidcLoadResult:
    enabled_requested: bool
    configured_fields: tuple
    secret_values_retained: bool
    config: ObservationOidcConfig

    def public_view(self):
        reason = self.config.disabled_reason()
        return {
            'google_client_type': GOOGLE_CLIENT_TYPE,
            'token_endpoint_auth_method': TOKEN_ENDPOINT_AUTH_METHOD,
            'enabled_requested': self.enabled_requested,
            'effective_enabled': reason is None,
            'disabled_reason': reason,
            'configured_fields': self.configured_fields,
            'client_secret_present': 'client_secret' in self.configured_fields,
            'session_secret_present': 'session_secret' in self.configured_fields,
            'secret_values_retained': self.secret_values_retained,
        }

    def __repr__(self):
        return 'ObservationOidcLoadResult(' + repr(self.public_view()) + ')'


def load_observation_oidc_settings(environ=None):
    """Load settings from ``environ`` or, when omitted, ``os.environ``.

    The returned config is effective only when the enable flag is exactly
    ``true`` and every required field validates.  Providing a client id or
    client secret without that flag does not enable the feature and does not
    keep those values.
    """
    source = os.environ if environ is None else environ
    configured = tuple(name for name, key in _FIELD_ENV if key in source)
    enabled_requested = source.get(ENV_ENABLED) == 'true'
    if not enabled_requested:
        return ObservationOidcLoadResult(
            enabled_requested=False,
            configured_fields=configured,
            secret_values_retained=False,
            config=ObservationOidcConfig({'enabled': False}),
        )
    allowlist, allow_error = _allowlist(source.get(ENV_ALLOWLIST))
    ttl, ttl_error = _ttl(source.get(ENV_SESSION_TTL))
    load_error = allow_error or ttl_error
    if load_error is not None:
        return ObservationOidcLoadResult(
            enabled_requested=True,
            configured_fields=configured,
            secret_values_retained=False,
            config=ObservationOidcConfig({'enabled': True}, load_error=load_error),
        )
    config = ObservationOidcConfig({
        'enabled': True,
        'issuer': EXPECTED_ISSUER,
        'client_id': source.get(ENV_CLIENT_ID) or '',
        'client_secret': source.get(ENV_CLIENT_SECRET) or '',
        'redirect_uri': source.get(ENV_REDIRECT_URI) or '',
        'session_secret': source.get(ENV_SESSION_SECRET) or '',
        'allowlist': allowlist,
        'session_ttl_seconds': ttl,
    })
    return ObservationOidcLoadResult(
        enabled_requested=True,
        configured_fields=configured,
        secret_values_retained=True,
        config=config,
    )


def _unique_object(pairs):
    parsed = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError('duplicate')
        parsed[key] = value
    return parsed


def _allowlist(raw):
    if raw is None or raw == '':
        return [], None
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > _MAX_ALLOWLIST_BYTES:
        return [], 'MALFORMED_ALLOWLIST'
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return [], 'MALFORMED_ALLOWLIST'
    if not isinstance(parsed, list):
        return [], 'MALFORMED_ALLOWLIST'
    return parsed, None


def _ttl(raw):
    if raw is None:
        return 600, None
    if not isinstance(raw, str) or not raw.isdigit():
        return 600, 'INVALID_CONFIGURATION'
    value = int(raw)
    if value < 30 or value > 86400:
        return 600, 'INVALID_CONFIGURATION'
    return value, None
