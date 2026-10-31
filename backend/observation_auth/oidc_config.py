"""Observation OIDC settings.

The flow is disabled unless a caller supplies a complete config object.
This module does not read process environment or production files.
"""
from tools.work_aa.observation_operator_identity import (
    BOT_START_PERMISSION, LITERAL_SUBJECT, LIVE_ARM_PERMISSION, OBSERVATION_PERMISSION)


EXPECTED_ISSUER = 'https://accounts.google.com'
AUTHORIZATION_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
JWKS_URI = 'https://www.googleapis.com/oauth2/v3/certs'
CLOCK_SKEW_SECONDS = 60
SECRET_FIELDS = (
    'client_secret', 'private_key', 'id_token', 'access_key', 'passphrase',
    'seed', 'password', 'credential',
)


class ObservationOidcConfig:
    def __init__(self, mapping=None):
        raw = dict(mapping or {})
        self._secret = any(name in raw for name in SECRET_FIELDS)
        self.enabled = raw.get('enabled') is True
        self.issuer = raw.get('issuer') or ''
        self.client_id = raw.get('client_id') or ''
        self.redirect_uri = raw.get('redirect_uri') or ''
        self.session_secret = raw.get('session_secret') or ''
        self.allowlist = tuple(raw.get('allowlist') or ())
        self.secure_cookie = raw.get('secure_cookie') is not False
        self.insecure_redirect_allowed = raw.get('insecure_redirect_allowed') is True
        self.clock_skew_seconds = CLOCK_SKEW_SECONDS
        self.transaction_ttl_seconds = 300
        self.session_ttl_seconds = int(raw.get('session_ttl_seconds') or 600)

    def disabled_reason(self):
        if self._secret:
            return 'SECRET_CONFIG_REJECTED'
        if not self.enabled:
            return 'FEATURE_DISABLED'
        if self.issuer != EXPECTED_ISSUER:
            return 'INVALID_ISSUER'
        if not self.client_id:
            return 'MISSING_CONFIGURATION'
        if not self.redirect_uri.startswith('https://') and not (
                self.insecure_redirect_allowed and self.redirect_uri.startswith('http://testserver/')):
            return 'INVALID_REDIRECT_URI'
        if '/api/observation/auth/oidc/callback' not in self.redirect_uri:
            return 'INVALID_REDIRECT_URI'
        if len(self.session_secret) < 16:
            return 'MISSING_SESSION_SECRET'
        if not self.allowlist:
            return 'MISSING_ALLOWLIST'
        for entry in self.allowlist:
            if not isinstance(entry, dict):
                return 'MISSING_ALLOWLIST'
            if entry.get('issuer') != EXPECTED_ISSUER:
                return 'INVALID_ISSUER'
            subject = entry.get('subject')
            if not isinstance(subject, str) or not subject or subject == LITERAL_SUBJECT:
                return 'MISSING_ALLOWLIST'
            if entry.get('permission') in (LIVE_ARM_PERMISSION, BOT_START_PERMISSION):
                return 'UNAUTHORIZED_PERMISSION'
            if entry.get('permission') != OBSERVATION_PERMISSION:
                return 'MISSING_PERMISSION'
        return None
